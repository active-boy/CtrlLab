import os
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import sympy as sp
from sympy.parsing.latex import parse_latex

app = Flask(__name__)
CORS(app)
WEB_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist'))
s, t, K = sp.symbols('s t K')


def parse_expr(value, latex=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('请输入表达式。')
    expr = parse_latex(value) if latex else sp.sympify(value, locals={'s': s, 't': t, 'K': K})
    return expr


def result(expr):
    return {'latex': sp.latex(expr), 'expression': str(expr)}


@app.get('/')
def home():
    return send_from_directory(WEB_DIST, 'index.html')


@app.get('/<path:filename>')
def frontend_files(filename):
    if filename.startswith('api/'):
        return jsonify({'error': '接口不存在。'}), 404
    requested = os.path.join(WEB_DIST, filename)
    if os.path.isfile(requested):
        return send_from_directory(WEB_DIST, filename)
    return send_from_directory(WEB_DIST, 'index.html')


@app.errorhandler(Exception)
def handle_error(error):
    return jsonify({'error': str(error) or '无法处理该表达式，请检查输入格式。'}), 400


@app.post('/api/transform')
def transform():
    data = request.get_json(force=True)
    expr = parse_expr(data.get('expression'), data.get('latex', False))
    mode = data.get('mode')
    if mode == 'laplace':
        out = sp.laplace_transform(expr, t, s, noconds=True)
    elif mode == 'inverse':
        out = sp.inverse_laplace_transform(expr, s, t)
    else:
        raise ValueError('未知的变换类型。')
    return jsonify(result(sp.simplify(out)))


@app.post('/api/transfer')
def transfer():
    data = request.get_json(force=True)
    expr = sp.cancel(parse_expr(data.get('expression'), data.get('latex', False)))
    numerator, denominator = sp.fraction(expr)
    zeros = sp.solve(numerator, s)
    poles = sp.solve(denominator, s)
    return jsonify({
        'rational': result(expr),
        'zero_pole': {'latex': sp.latex(sp.Mul(*[s-z for z in zeros]) / sp.Mul(*[s-p for p in poles])), 'expression': str(sp.Mul(*[s-z for z in zeros]) / sp.Mul(*[s-p for p in poles]))},
        'zeros': [str(z) for z in zeros], 'poles': [str(p) for p in poles],
        'note': '零极点形式当前展示根因子；增益及重根信息将在后续完善。'
    })


@app.post('/api/time-domain')
def time_domain():
    data = request.get_json(force=True)
    G = sp.cancel(parse_expr(data.get('expression'), data.get('latex', False)))
    typ = data.get('input', 'step')
    band = float(data.get('settling_band', 0.02))
    if band not in (0.02, 0.05): raise ValueError('调节时间误差带仅支持 2% 或 5%。')
    num, den = sp.Poly(sp.fraction(G)[0], s), sp.Poly(sp.fraction(G)[1], s)
    if den.degree() < 1:
        raise ValueError('请输入分母次数至少为 1 的传递函数。')
    # Routh array with symbolic-safe epsilon handling for zero first elements.
    rows = [[sp.S.Zero] * (den.degree() + 1) for _ in range(den.degree() + 1)]
    coeff = den.all_coeffs()
    rows[0][:len(coeff[::2])] = coeff[::2]
    rows[1][:len(coeff[1::2])] = coeff[1::2]
    eps = sp.Symbol('ε', positive=True)
    for i in range(2, len(rows)):
        if rows[i-1][0] == 0:
            rows[i-1][0] = eps
        for j in range(den.degree() - 1):
            rows[i][j] = sp.simplify((rows[i-1][0]*rows[i-2][j+1]-rows[i-2][0]*rows[i-1][j+1])/rows[i-1][0])
    first = [sp.limit(row[0], eps, 0, dir='+') for row in rows]
    signs = [sp.sign(x) for x in first]
    rhp = sum(1 for a,b in zip(signs, signs[1:]) if a*b == -1)
    stable = all(x.is_positive for x in first) or all(x.is_negative for x in first)
    inp = {'step': 1/s, 'ramp': 1/s**2, 'parabolic': 1/s**3}.get(typ)
    if inp is None: raise ValueError('输入类型无效。')
    error = sp.cancel(1/(1+G*(1 if data.get('feedback','negative')=='negative' else -1)))
    loop = sp.cancel(G/(1+G*(1 if data.get('feedback','negative')=='negative' else -1)))
    ess = sp.limit(s*error*inp, s, 0, dir='+')
    response = sp.inverse_laplace_transform(sp.cancel(loop*inp), s, t)
    poles = sp.solve(den.as_expr(), s)
    # Numerical step metrics from the closed-loop response, when real-valued and stable.
    metrics = {}
    try:
        import numpy as np
        f = sp.lambdify(t, response, 'numpy')
        tv = np.linspace(0, 100, 30000)
        y = np.asarray(f(tv), dtype=float)
        y = np.real_if_close(y).astype(float)
        yf = float(y[-1]); peak_i = int(np.argmax(y)); peak = float(y[peak_i])
        metrics = {'final_value': yf, 'rise_time_10_90': float(tv[np.where(y >= .9*yf)[0][0]]-tv[np.where(y >= .1*yf)[0][0]]) if yf else None,
                   'peak_time': float(tv[peak_i]), 'overshoot_percent': max(0., (peak-yf)/abs(yf)*100) if yf else None,
                   'settling_time': next((float(tv[i]) for i in range(len(tv)) if np.all(np.abs(y[i:]-yf)<=band*max(abs(yf),1e-12))), None)}
    except Exception:
        metrics = {'note': '响应无法稳定数值化；可查看解析响应和极点后判断。'}
    degree = den.degree()
    order_info = '一阶系统' if degree == 1 else ('二阶系统' if degree == 2 else '高阶系统')
    special = []
    if degree == 1:
        pole = sp.solve(den.as_expr(), s)[0]
        special = [f'一阶极点 p = {pole}', f'时间常数 τ = {-1/pole}', '单位阶跃无超调；稳定一阶系统的 2% 调节时间近似为 4τ，5% 调节时间近似为 3τ。']
    elif degree == 2:
        a,b,c = den.all_coeffs()
        wn = sp.sqrt(c/a); zeta = sp.simplify(b/(2*sp.sqrt(a*c)))
        special = [f'自然频率 ω_n = {wn}', f'阻尼比 ζ = {zeta}', '欠阻尼二阶系统：振荡频率 ω_d = ω_n√(1−ζ²)，超调量 M_p = exp(−πζ/√(1−ζ²))×100%。', f'按所选误差带近似调节时间 t_s ≈ −ln({band})/(ζω_n)。']
    return jsonify({'order_info': order_info, 'special_rules': special, 'settling_band': band, 'routh': [[str(sp.simplify(v)) for v in row] for row in rows], 'first_column': [str(x) for x in first],
        'rhp_poles': rhp, 'stable': stable, 'poles': [str(x) for x in poles], 'steady_error': str(ess),
        'response': result(sp.simplify(response)), 'metrics': metrics,
        'steps': [f'闭环传递函数 T(s) = {sp.sstr(loop)}', f'误差传递关系 E(s)/R(s) = {sp.sstr(error)}',
                  f'按终值定理 e_ss = lim(s→0) s E(s) = {ess}', '劳斯表首列符号变化次数等于右半平面极点数。']})


@app.post('/api/frequency-domain')
def frequency_domain():
    import numpy as np
    data = request.get_json(force=True)
    G = sp.cancel(parse_expr(data.get('expression'), data.get('latex', False)))
    wmin = float(data.get('wmin', 0.01)); wmax = float(data.get('wmax', 1000))
    if not (0 < wmin < wmax): raise ValueError('频率范围须满足 0 < 最小值 < 最大值。')
    w = np.logspace(np.log10(wmin), np.log10(wmax), 700)
    fn = sp.lambdify(s, G, modules='numpy')
    H = np.asarray(fn(1j*w), dtype=complex)
    H = np.broadcast_to(H, w.shape)
    mag = np.abs(H); phase = np.unwrap(np.angle(H))*180/np.pi
    db = 20*np.log10(np.maximum(mag, 1e-300))
    # Estimate gain crossover and phase crossover by linear interpolation.
    def crossing(x, y, level):
        idx = np.where((y[:-1]-level)*(y[1:]-level) <= 0)[0]
        out=[]
        for i in idx:
            if y[i+1] == y[i]: continue
            a=(level-y[i])/(y[i+1]-y[i]); out.append(float(np.exp(np.log(x[i])+a*(np.log(x[i+1])-np.log(x[i])))))
        return out
    wcg=crossing(w,db,0); wcp=crossing(w,phase,-180)
    gm_db=None; pm=None; gm_freq=wcp[0] if wcp else None; pm_freq=wcg[0] if wcg else None
    if gm_freq is not None:
        gm_db=float(-np.interp(np.log(gm_freq),np.log(w),db))
    if pm_freq is not None:
        pm=float(180+np.interp(np.log(pm_freq),np.log(w),phase))
    points=[{'w':float(x),'db':float(y),'phase':float(z),'re':float(h.real),'im':float(h.imag)} for x,y,z,h in zip(w,db,phase,H)]
    return jsonify({'expression':result(G),'points':points,'margins':{'gain_margin_db':gm_db,'phase_margin_deg':pm,'gain_crossovers':wcg,'phase_crossovers':wcp},
      'note':'稳定裕度由所选频率范围内的交越频率数值插值估算；若未找到交越，裕度显示为空。','steps':['令 s=jω，将传递函数代入频率轴。','幅值比 |G(jω)| 转为 dB：20 log₁₀|G(jω)|。','相角对频率展开，避免 ±180° 跳变。','相位裕度在增益交越频率 |G|=1 处计算；增益裕度在相位交越频率 ∠G=−180° 处计算。']})


@app.post('/api/root-locus')
def root_locus():
    import numpy as np
    data = request.get_json(force=True)
    G = sp.cancel(parse_expr(data.get('expression'), data.get('latex', False)))
    feedback = data.get('feedback', 'negative')
    if feedback not in ('negative', 'positive'):
        raise ValueError('反馈类型无效。')
    kvalue = float(data.get('gain', 1))
    numerator, denominator = sp.fraction(G)
    pn, pd = sp.Poly(numerator, s), sp.Poly(denominator, s)
    if pn.degree() < 0 or pd.degree() < 1:
        raise ValueError('请输入 proper 有理传递函数。')
    if not all(not c.free_symbols for c in pn.all_coeffs() + pd.all_coeffs()):
        raise ValueError('请先将传递函数中的参数替换为数值。')
    nc = np.array([float(sp.N(c)) for c in pn.all_coeffs()])
    dc = np.array([float(sp.N(c)) for c in pd.all_coeffs()])
    if len(nc) > len(dc):
        raise ValueError('根轨迹当前要求分子阶次不高于分母阶次。')
    nc = np.pad(nc, (len(dc)-len(nc), 0))
    sign = 1 if feedback == 'negative' else -1
    poles = np.roots(dc); zeros = np.roots(np.trim_zeros(nc, 'f')) if np.any(nc) else np.array([])
    n, m = len(poles), len(zeros)
    kvals = np.concatenate(([0.0], np.logspace(-4, 4, 220)))
    tracks = []
    for kval in kvals:
        roots = np.roots(dc + sign*kval*nc)
        if not tracks:
            tracks = [[z] for z in roots]
        else:
            previous = [branch[-1] for branch in tracks]
            remaining = set(range(len(roots)))
            for i, old in enumerate(previous):
                j = min(remaining, key=lambda q: abs(roots[q]-old))
                tracks[i].append(roots[j]); remaining.remove(j)
    real_values = sorted([float(z.real) for z in np.concatenate((poles, zeros)) if abs(z.imag)<1e-8])
    intervals = []
    bounds = [-np.inf] + real_values + [np.inf]
    for left, right in zip(bounds[:-1], bounds[1:]):
        probe = right-1 if np.isinf(left) else left+1 if np.isinf(right) else (left+right)/2
        if sum(x > probe for x in real_values) % 2:
            intervals.append([None if np.isinf(left) else left, None if np.isinf(right) else right])
    angles = [(2*q+1)*180/(n-m) for q in range(n-m)] if n>m else []
    centroid = (sum(poles)-sum(zeros))/(n-m) if n>m else None
    kval_expr = sp.cancel(-sp.denom(G)/sp.together(sp.fraction(G)[0]))
    bp_expr = sp.together(sp.diff(kval_expr, s)).as_numer_denom()[0]
    breakpoints=[]
    for x in sp.solve(bp_expr, s):
        try:
            xv=complex(sp.N(x)); kv=float(sp.N(kval_expr.subs(s,x)))
            if abs(xv.imag)<1e-8 and kv>=0: breakpoints.append({'s':float(xv.real),'K':kv})
        except Exception:
            pass
    roots_now=np.roots(dc+sign*kvalue*nc)
    angle_info=[]
    for p in poles:
        other_poles=[q for q in poles if abs(q-p)>1e-8]
        zsum=sum(np.angle(p-z,deg=True) for z in zeros)
        psum=sum(np.angle(p-q,deg=True) for q in other_poles)
        angle_info.append({'point':str(complex(p)),'kind':'起始角','deg':float((180+zsum-psum+(180 if feedback=='positive' else 0))%360)})
    for z in zeros:
        other_zeros=[q for q in zeros if abs(q-z)>1e-8]
        psum=sum(np.angle(z-p,deg=True) for p in poles)
        zsum=sum(np.angle(z-q,deg=True) for q in other_zeros)
        angle_info.append({'point':str(complex(z)),'kind':'终止角','deg':float((180+zsum-psum+(180 if feedback=='positive' else 0))%360)})
    characteristic=sp.Poly(sp.expand(sp.denom(G)+sign*K*sp.together(sp.fraction(G)[0])),s)
    coeff=characteristic.all_coeffs()
    axis_cross=[]
    for kval in np.logspace(-4,4,600):
        for z in np.roots(dc+sign*kval*nc):
            if abs(z.real)<0.002 and z.imag>0:
                axis_cross.append({'K':float(kval),'omega':float(z.imag)})
    crossing=min(axis_cross,key=lambda x:abs(x['K']-kvalue)) if axis_cross else None
    cdata=lambda z:{'re':float(np.real(z)),'im':float(np.imag(z))}
    return jsonify({'branch_count':int(n),'poles':[cdata(z) for z in poles],'zeros':[cdata(z) for z in zeros],
        'gain_grid':[float(x) for x in kvals],'tracks':[[cdata(z) for z in tr] for tr in tracks],
        'current_gain':kvalue,'current_poles':[cdata(z) for z in roots_now],'feedback':feedback,
        'asymptote_angles_deg':angles,'asymptote_centroid':cdata(centroid) if centroid is not None else None,
        'real_axis_intervals':intervals,'break_points':breakpoints,'angles':angle_info,'axis_crossing':crossing,
        'pole_sum':str(sp.simplify(-coeff[1]/coeff[0])) if len(coeff)>1 else '0',
        'steps':['支数等于开环极点数 n。起点为开环极点，终点为开环零点；n−m 条分支趋于无穷远。',
        '负反馈特征方程为 D(s)+KN(s)=0；正反馈特征方程为 D(s)−KN(s)=0。',
        '渐近线重心为 (开环极点和−开环零点和)/(n−m)，渐近线角度按 (2q+1)180°/(n−m) 计算。',
        '实轴根轨迹区间使用其右侧实极点与实零点总数为奇数的判据。',
        '分离/会合点候选解由 dK(s)/ds=0 求出，并仅保留实数且 K≥0 的点。',
        '起始角、终止角由极点/零点向量角度和角度条件计算；与虚轴交点由闭环极点扫描估算。',
        '闭环极点之和由特征多项式系数的韦达关系计算。']})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')), debug=False)

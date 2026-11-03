# CtrlLab

CtrlLab 是一个面向自动控制原理学习的 H5 交互式分析平台。当前包括函数处理、时域分析、频域分析和根轨迹四个栏目。表达式输入使用 MathLive，符号计算使用 Flask 与 SymPy。

## 本地运行

需要 Python 3.10+ 和 Node.js 18+。

1. 后端：在 `backend` 安装 `requirements.txt`，运行 `python app.py`（默认 `127.0.0.1:5000`）。
2. 前端：进入 `frontend`，运行 `npm install` 和 `npm run dev`。
3. 打开 Vite 提示的地址。前端开发服务器会将 `/api` 请求代理到本地 Flask。

## 栏目

- 函数处理：Laplace 及逆变换、传递函数表示。
- 时域分析：稳态分析、劳斯表、一般瞬态以及一阶/二阶特性。
- 频域分析：Bode、Nyquist 与稳定裕度。
- 根轨迹：正/负反馈切换、增益调节和根轨迹特征。

页面顶部的“全局表达式”开关控制四个栏目是否共用 MathLive 输入；开关和表达式保存在当前浏览器本地。

## Netlify 部署前端

Netlify 使用仓库根目录的 `netlify.toml` 自动构建 H5 前端。设置环境变量 `VITE_API_BASE_URL` 为已部署 Flask 服务的 HTTPS 根地址（不要在末尾加 `/`）。Flask 服务需允许 Netlify 域名跨域访问。GitHub 仓库本身不托管 Flask 运行进程。

## 微信云托管

仓库根目录的 `Dockerfile` 会先构建 H5，再运行 Flask，并由同一个服务提供网页和 `/api` 接口。监听端口默认为 5000，可通过 `PORT` 环境变量调整。

在微信云托管创建服务后，进入服务详情并新建版本，选择“代码库拉取”，授权 GitHub 并选择 `active-boy/CtrlLab` 的 `main` 分支。构建目录选仓库根目录 `.`，Dockerfile 填 `Dockerfile`，容器端口填 `5000)。首次部署建议先创建版本，查看构建和运行日志后再开放流量。

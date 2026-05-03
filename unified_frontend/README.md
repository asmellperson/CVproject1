# React + TypeScript + Vite

cd /usr/zyy/Fuda_CVPreject/unified_frontend
  
npm run dev

  npm install

  启动后访问：

  http://localhost:3000

  如果是在服务器上跑，浏览器访问：

  http://<服务器IP>:3000

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```


## 开发启动与公网域名

```bash
npm install
npm run dev
```

默认监听：`0.0.0.0:3000`

浏览器访问：`http://<服务器IP>:3000`

调试时可用命令行临时覆盖端口：

```bash
npm run dev -- --port <前端调试端口>
```

生产公网域名：`https://aicv.fudar.com/`

### 代理后端

前端开发环境已代理以下路径：
- `/api` -> `VITE_BACKEND_TARGET`
- `/api/aivision`、`/api/ai` -> `VITE_AIVISION_BACKEND_TARGET`
- `/aivision` -> `VITE_AIVISION_BACKEND_TARGET`
- `/ws` -> `VITE_BACKEND_TARGET`

默认后端代理目标：
- Guard Room: `http://127.0.0.1:5000`
- AiVision: `http://127.0.0.1:7862`
- Security VLM: `http://127.0.0.1:8000`

调试时可用本地环境变量临时覆盖代理目标：

```bash
VITE_BACKEND_TARGET=http://127.0.0.1:<GuardRoom调试端口> \
VITE_AIVISION_BACKEND_TARGET=http://127.0.0.1:<AiVision调试端口> \
VITE_SECURITY_VLM_BACKEND_TARGET=http://127.0.0.1:<SecurityVlm调试端口> \
npm run dev -- --port <前端调试端口>
```

如需修改后端地址，可复制 `.env.example` 为 `.env` 后调整：

```env
VITE_DEV_PORT=3000
VITE_PUBLIC_ORIGIN=https://aicv.fudar.com
VITE_BACKEND_TARGET=http://127.0.0.1:5000
VITE_AIVISION_BACKEND_TARGET=http://127.0.0.1:7862
VITE_SECURITY_VLM_BACKEND_TARGET=http://127.0.0.1:8000
VITE_API_BASE=https://aicv.fudar.com
VITE_WS_BASE=wss://aicv.fudar.com
VITE_AIVISION_URL=https://aicv.fudar.com/aivision/
```

# Course Frontend (+ FastAPI backend)

이 리포지토리는 **Vite(React) 프론트엔드**와 `backend/`의 **FastAPI(text-to-sql) 백엔드**를 함께 담고 있습니다.

## 실행 방법 (개발)

### 프론트 + 백엔드 같이 실행

```bash
npm install
python -m pip install -r backend/requirements.txt
npm run dev:full
```

- 프론트: `http://localhost:5173`
- 백엔드: `http://127.0.0.1:8000`
- 백엔드 헬스체크: `GET /api/v1/health`

### 환경변수

- 프론트: `.env` (예시는 `.env.example`)
  - `VITE_API_BASE_URL=/api/v1` 권장 (Vite proxy로 백엔드로 전달)
- 백엔드: `backend/.env` (예시는 `backend/.env.example`)
  - `OLLAMA_BASE_URL` (기본 `http://127.0.0.1:11434`)
  - `OLLAMA_MODEL` (예: `text2sql-local`)
  - `DATABASE_URL` (예: `postgresql://postgres:1234@localhost:5432/univ`)
  - `REDIS_URL` (선택)

> `DATABASE_URL`이 없으면 `/api/v1/query`는 에러를 반환하지만, 서버는 기동됩니다.

### 로컬 모델(Ollama) 준비

```bash
ollama create text2sql-local -f "C:\충남대\4-1\종합설계\작업\모델\Modelfile"
ollama run text2sql-local
```

- `Modelfile`의 `FROM` 경로는 실제 `gguf` 위치로 맞춰야 합니다.
- API(OpenAI) 기반 백업 코드는 `backend/backup_api/`에 남겨뒀습니다.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

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

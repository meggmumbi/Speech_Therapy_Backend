# Study console

The researcher's desk-side surface. See `../docs/CONSOLE.md` for scope.

## Run

```
cd console
npm install
npm run dev          # http://localhost:5173, proxies /api -> http://localhost:8000
```

Set `BACKEND_URL` to point the dev proxy elsewhere. For a production build,
set `VITE_API_URL` to the backend's base URL (with trailing slash) and run
`npm run build`; the output in `dist/` is static.

## What is in step 1

- Sign in with the same account as the tablet app.
- Participants: list, enrol, edit, delete (only while they have no sessions).
- Per participant: assignment with the current cell counts beside the button,
  exclusion with a reason, the five-step protocol as the server reports it,
  and questionnaire means by block.
- Balance: cells, block-1 condition and list splits, and the word-list
  binding.

Steps 2 to 4 (stimulus tables, model-audio recording, dashboard) follow.

# Front-end build

`scene.src.js` is the source of the 3D line view. The bundle `app/static/scene.js` is committed, so the application and the
container image need no Node.js. Rebuild after changing the source:

```bash
cd frontend
npm install
npm run build
```

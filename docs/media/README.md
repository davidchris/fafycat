# README Media

This folder contains the generated README demo assets:

- `fafycat-demo.gif`
- `home.png`
- `review-queue.png`
- `analytics.png`
- `demo-import.csv`

To regenerate the assets from a clean synthetic demo state:

```bash
./scripts/capture_readme_demo.sh
```

The script starts an isolated dev server, trains the local model, imports the curated demo CSV, captures the UI with Playwright, and renders the final annotated media files.

# CloudShell Marketing Website

Static marketing website for the CloudShell project.

## Structure

```text
website/
├── index.html        # Main page
├── style.css         # All styles
├── favicon.svg       # Site favicon
└── images/           # Populated at deploy time from repo-root images/
```

The `images/` directory is **not committed** to the website folder. The GitHub
Actions workflow copies `images/` from the repository root into `website/images/`
before uploading the Pages artifact, keeping binary files out of this subtree and
avoiding unnecessary Git LFS storage.

## Google Search Console

To enable Google Search Console verification, set the `GOOGLE_SITE_VERIFICATION`
repository secret in GitHub. The workflow will inject the meta tag automatically
before deploying to GitHub Pages.

The tag format expected by the workflow is the **full meta tag string**, e.g.:

```html
<meta name="google-site-verification" content="XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" />
```

## Local preview

Copy the root-level screenshots first, then serve the folder:

```bash
cp -r images/ website/images/
python3 -m http.server 8000 --directory website/
# Then open http://localhost:8000
```

## Deployment

Pushed to `main` the `pages.yml` workflow builds and publishes the site to
GitHub Pages automatically. See `.github/workflows/pages.yml`.

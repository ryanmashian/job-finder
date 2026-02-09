# Push to GitHub (gh CLI not installed)

Git is initialized and the initial commit is done. To create the repo and push:

## 1. Create the repo on GitHub

1. Go to **https://github.com/new**
2. **Repository name:** `job-finder`
3. Choose **Public**
4. Do **not** add a README, .gitignore, or license (we already have them)
5. Click **Create repository**

## 2. Add remote and push

In a terminal, from the project folder (`c:\Users\Ryanm\OneDrive\Desktop\job-finder`), run (replace **YOUR_USERNAME** with your GitHub username):

```bash
git remote add origin https://github.com/YOUR_USERNAME/job-finder.git
git branch -M main
git push -u origin main
```

If your default branch is already `master` and you want to keep it:

```bash
git remote add origin https://github.com/YOUR_USERNAME/job-finder.git
git push -u origin master
```

GitHub’s default is `main`; this repo’s first branch is `master`. Either push `master` and use it, or rename to `main` with `git branch -M main` then push.

Done. Your code will be at `https://github.com/YOUR_USERNAME/job-finder`.

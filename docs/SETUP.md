# Setting up the weekly pipeline

Every Monday, `.github/workflows/weekly.yml` checks kaikki.org for a new Wiktionary dump. If there
is one, it rebuilds the site's data, loads it into BigQuery, runs dbt (snapshots, marts, data
tests) and, only if every test passes, deploys the site to Cloudflare Pages.

```text
GitHub Actions ──(short-lived token, no key file)──► Google Cloud: BigQuery ◄── dbt
      │
      └──(API token)──► Cloudflare Pages: the website
```

You set up four things, in this order: try it locally, a Google Cloud project, a way for GitHub to
sign in to it, and the Cloudflare token. Then you store the names and tokens in GitHub and run
the job once by hand. Plan on about an hour, plus 1–2 hours for the first run.

**What it costs:** nothing, in practice. BigQuery's free tier covers 10 GB of storage and 1 TB of
queries a month; this uses about 5 GB and a few GB of queries a week. Cloudflare Pages is free.
GitHub Actions is free for public repositories (a private one gets 2,000 minutes a month, and a
run takes about 2 hours, so about 9 hours a month). Google still requires a billing account, so
step 2 also sets a budget alert.

---

## 0. What you need

- [ ] The `gcloud` command-line tool: `brew install --cask google-cloud-sdk`
- [ ] The `gh` command-line tool (optional, for step 5): `brew install gh`, then `gh auth login`
- [ ] A Google account you can add a payment method to
- [ ] Your Cloudflare account, with the `etymodendron` Pages project that `npm run deploy` already uses

## 1. Try the warehouse locally first (free, no accounts)

This checks the loader and dbt on your laptop with duckdb before anything costs money or needs
credentials. It needs `data/work` and `data/out`, which you already have from running the pipeline.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-warehouse.txt
.venv/bin/python -m etl.warehouse load --backend duckdb
cd warehouse && ../.venv/bin/dbt build --profiles-dir . && cd ..
```

`dbt build` should end with every model, snapshot and test passing. If it doesn't, fix that
first: the cloud runs the same thing.

## 2. Create the Google Cloud project

Pick a project ID: lowercase, globally unique, for example `etymodendron-4821`. The commands below
use shell variables so you only type it once; run them all in the same terminal window.

```bash
gcloud auth login
export PROJECT_ID=etymodendron-4821        # your choice
gcloud projects create $PROJECT_ID
```

**Turn on billing.** The BigQuery sandbox (no billing) deletes tables after 60 days, which would
delete the snapshot history.

```bash
gcloud billing accounts list               # copy the ACCOUNT_ID; create one in the console if the list is empty
gcloud billing projects link $PROJECT_ID --billing-account=XXXXXX-XXXXXX-XXXXXX
```

**Turn on the APIs** the job uses: BigQuery, and the three that let GitHub sign in (step 4).

```bash
gcloud services enable bigquery.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com --project $PROJECT_ID
```

**Set a budget alert** so a mistake can't run up a bill unnoticed: in the
[Cloud console](https://console.cloud.google.com/billing), open Billing → Budgets & alerts →
Create budget, scope it to this project, set $5, and keep the default email alerts. (An alert
emails you; it does not stop spending.)

## 3. Try BigQuery from your laptop

This is step 1 again, pointed at BigQuery. It proves the project works before GitHub is involved,
and it loads your current dump so the history starts now.

```bash
gcloud auth application-default login      # lets local tools act as you
export GCP_PROJECT=$PROJECT_ID
.venv/bin/python -m etl.warehouse load --backend bigquery
cd warehouse && DBT_TARGET=prod ../.venv/bin/dbt build --profiles-dir . && cd ..
```

In the [BigQuery console](https://console.cloud.google.com/bigquery) you should now see two
datasets: `etymodendron_raw` (the four `raw_*` tables the loader wrote) and `etymodendron` (dbt's
staging views, snapshots and marts). Try:

```sql
select * from etymodendron.fct_dump_summary order by dump_id desc;
```

The data location defaults to `US`. To use another (for example `EU`), set `BQ_LOCATION` before
the first load and add the same GitHub variable in step 5. Datasets can't move after they're made.

## 4. Let GitHub sign in to Google, with no key file

The usual shortcut is to download a service account key and paste it into GitHub. Don't: it's a
password that never expires. Workload Identity Federation does the same job with tokens that
last an hour: GitHub proves to Google *which repository* is running, and Google allows only
yours.

```bash
export REPO=luangia/Etymodendron           # owner/name, exactly as on GitHub
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
export SA=etymodendron-ci@$PROJECT_ID.iam.gserviceaccount.com
```

**A service account** for the job, allowed to write BigQuery tables and run queries, nothing more:

```bash
gcloud iam service-accounts create etymodendron-ci --project $PROJECT_ID \
  --display-name "Etymodendron weekly job"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member serviceAccount:$SA --role roles/bigquery.dataEditor
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member serviceAccount:$SA --role roles/bigquery.jobUser
```

**A workload identity pool and provider** that trusts GitHub's sign-in tokens, but only from
your repository (the `--attribute-condition`):

```bash
gcloud iam workload-identity-pools create github --project $PROJECT_ID \
  --location global --display-name "GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc etymodendron --project $PROJECT_ID \
  --location global --workload-identity-pool github --display-name "Etymodendron repo" \
  --issuer-uri https://token.actions.githubusercontent.com \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository == '$REPO'"
```

**Let runs from your repository act as the service account:**

```bash
gcloud iam service-accounts add-iam-policy-binding $SA --project $PROJECT_ID \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"
```

**Print the two values GitHub needs** and keep them for step 5:

```bash
echo "GCP_WORKLOAD_IDENTITY_PROVIDER = projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/etymodendron"
echo "GCP_SERVICE_ACCOUNT            = $SA"
```

## 5. Cloudflare: an API token for deploys

On your laptop, `wrangler` uses your login. In GitHub it needs a token.

1. In the Cloudflare dashboard, open **My Profile → API Tokens → Create Token → Create Custom Token**.
2. Name it `etymodendron deploy`. Under **Permissions**, choose **Account → Cloudflare Pages → Edit**.
   Under **Account Resources**, choose your account. Create it and copy the token: it's shown once.
3. Find your **account ID**: run `cd web && npx wrangler whoami`, or open Workers & Pages in the
   dashboard; it's in the right-hand column.

## 6. Store everything in GitHub

In the repository on GitHub: **Settings → Secrets and variables → Actions**.

| Kind | Name | Value |
|---|---|---|
| Variable | `GCP_PROJECT` | your project ID, e.g. `etymodendron-4821` |
| Variable | `BQ_LOCATION` | only if you chose something other than `US` in step 3 |
| Secret | `GCP_WORKLOAD_IDENTITY_PROVIDER` | the `projects/…/providers/etymodendron` line from step 4 |
| Secret | `GCP_SERVICE_ACCOUNT` | `etymodendron-ci@<project>.iam.gserviceaccount.com` |
| Secret | `CLOUDFLARE_API_TOKEN` | the token from step 5 |
| Secret | `CLOUDFLARE_ACCOUNT_ID` | the account ID from step 5 |

Or from the terminal, in the same window as steps 2–4 (`gh` asks for each secret's value):

```bash
gh variable set GCP_PROJECT --body "$PROJECT_ID"
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --body "projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/etymodendron"
gh secret set GCP_SERVICE_ACCOUNT --body "$SA"
gh secret set CLOUDFLARE_API_TOKEN
gh secret set CLOUDFLARE_ACCOUNT_ID
```

The project ID and service account email aren't secret on their own; they're stored as secrets
only to keep them out of the logs.

## 7. First run

Open the repository's **Actions** tab → **Weekly dump** → **Run workflow**. Tick **force**: step 3
already loaded the current dump, so without it the job would see nothing new and stop.

What to expect, in order:

| Step | Takes | If it fails |
|---|---|---|
| Google auth | seconds | see Troubleshooting |
| Is there a new dump? | seconds | the variable or secrets from step 6 |
| Download (about 3 GB) | 5–15 min | kaikki.org was down: run again later |
| Extract, build graph | 30–60 min | the same error locally: run `python -m etl.run` |
| Load into BigQuery | 5–10 min | permissions: step 4's roles |
| dbt build | 5–10 min | a data test: the guard did its job, see below |
| Deploy to Cloudflare | 2–5 min | the Cloudflare token or account ID |

When it's green, the site's About dialog shows the new dump date, and
`fct_dump_summary` has one more row. After that it runs every Monday at 07:00 UTC on its own.

**If a data test fails,** nothing was deployed and the live site still shows the last good data.
Look at the failing test's name in the dbt step's log, and the validation report the run kept
(under **Artifacts** on the run's page). `assert_coverage_not_dropping` and
`assert_section_count_stable` usually mean Wiktionary changed how something is written and the
parser needs updating. If the change is real and expected, raise the limits in
`warehouse/dbt_project.yml` (`vars`) and run the job again.

## Day to day

- **UI changes** don't need any of this: `cd web && npm run deploy` from your laptop, as before.
  The weekly job deploys only when there's a new dump.
- **Stop the weekly job:** Actions → Weekly dump → ⋯ → Disable workflow.
- **Look at history:** `fct_section_changes` and `fct_word_root_changes` in BigQuery show what
  changed between dumps.

## Troubleshooting

- **`Permission 'iam.serviceAccounts.getAccessToken' denied`** or **`unauthorized_client`** at
  the Google auth step: the repository in step 4 doesn't match exactly (owner and name,
  case-sensitive), or the `add-iam-policy-binding` for the service account was skipped. Changes
  to these can take a few minutes to apply.
- **`Access Denied: … bigquery.datasets.create`** or **`bigquery.jobs.create`**: one of the two
  roles in step 4 is missing.
- **`set --project or GCP_PROJECT`** at "Is there a new dump?" (or dbt's
  `Env var required but not provided: 'GCP_PROJECT'`): the repository variable is missing or
  misspelled. It's a *variable*, not a secret.
- **Cloudflare `Authentication error [code: 10000]`**: the token lacks *Cloudflare Pages → Edit*,
  or the account ID is wrong.
- **The job is killed or runs out of disk:** the runner has about 16 GB of memory and 14 GB of
  free disk; the pipeline peaks at about 5.3 GB of memory and the dump is 3 GB, so this points to
  a much larger dump than today's.

# AWS S3 Automated BI Pipeline — Static Web Dashboard

A two-tier cloud data pipeline that takes raw business datasets, processes them with Python and pandas, and publishes a live BI dashboard as a highly available static website — built to learn core AWS storage, security, and automation concepts hands-on.

---

## 1. What This Project Does

- Raw CSV data sits in a private S3 bucket — completely blocked from public access — which acts as our single source of truth.
- A Python script running on an EC2 instance reads the data directly into memory — bypassing local disk storage — where it cleans the records and calculates key metrics using pandas.
- The script generates a styled HTML report with KPI cards and a chart — and uploads it to a second, public S3 bucket.
- This secondary bucket is configured for static website hosting — the dashboard now refreshes automatically and instantly the moment a new CSV file is uploaded to the private bucket, with no manual intervention, no SSH, and no scheduled timer required.

---

## 2. Architecture

```
                    ┌─────────────────────────┐
                    │   S3 Bucket 1           │
                    │   s3-private-rawdata    │
                    │   (private vault)       │
                    │   Block Public: ON      │
                    │   Versioning: ON        │
                    └────────────┬────────────┘
                                 │ S3 Event Notification
                                 │ fires on .csv upload
                                 ▼
                    ┌─────────────────────────┐
                    │   AWS Lambda            │
                    │   t20_pipeline_trigger  │
                    │   reads filename from   │
                    │   S3 event payload      │
                    └────────────┬────────────┘
                                 │ SSM SendCommand
                                 │ passes exact filename
                                 ▼
                    ┌─────────────────────────┐
                    │   EC2 Instance          │
                    │   stage2_pipeline.py    │
                    │   extract → clean       │
                    │   build HTML → upload   │
                    └────────────┬────────────┘
                                 │ boto3.put_object()
                                 ▼
                    ┌─────────────────────────┐
                    │   S3 Bucket 2           │
                    │   s3-public-webhosting  │
                    │   (public website)      │
                    │   index.html updated    │
                    │   Static Website: ON    │
                    └─────────────────────────┘
```

---

## 3. Screenshots

### Lambda Trigger Connected to S3

<img width="2880" height="1616" alt="04" src="https://github.com/user-attachments/assets/039b525f-d5a9-4ef9-9917-1b5f71871c57" />

### SSM Command History — Automated Executions

<img width="2880" height="960" alt="03" src="https://github.com/user-attachments/assets/a5068c27-f26c-4a4a-a609-c3fc0420f7f2" />

### Live Dashboard — First CSV Upload (03:42 UTC)

<img width="2845" height="1713" alt="01" src="https://github.com/user-attachments/assets/4f00e1d3-2a22-44ae-901f-cdd5188eb93e" />

### Live Dashboard — Second CSV Upload (03:43 UTC, different data)

<img width="2876" height="1711" alt="02" src="https://github.com/user-attachments/assets/80158b77-af69-416d-824f-2eea8ea2cd97" />

> Two uploads, one minute apart, two completely different dashboards — fully automated with zero manual intervention.

---

## 4. Project Stages

### 4.1 Stage 1 — Manual Pipeline ✅

**Overview:** The foundational architecture is built entirely around manual execution to master baseline cloud infrastructure, data manipulation, and explicit permission mapping.

**Infrastructure Setup:** Both S3 buckets are provisioned manually via the AWS Console, and an explicit IAM role is attached to the EC2 instance to grant secure data access.

**Pipeline Execution:** The ETL lifecycle is triggered entirely by hand — requiring an active SSH connection to the EC2 instance to execute the Python script (`stage1_pipeline.py`).

**Data Refresh:** The static website remains fixed until a developer manually runs the script — making this manual step the clear problem statement that drives the need for future automation.

---

### 4.2 Stage 2 — Scheduled Automation ✅

**The Goal:** Eliminate the need for manual SSH intervention by transitioning to a hands-off, time-based schedule using EventBridge Scheduler.

**How It Works:** AWS EventBridge Scheduler fired on a fixed cadence and called the AWS Systems Manager (SSM) `SendCommand` API, which instructed the SSM Agent running on the EC2 instance to execute `stage2_pipeline.py` — no SSH, no manual trigger, no Lambda.

**Dynamic File Resolution:** Stage 1 hardcoded the CSV filename. Stage 2 introduced `get_latest_file()` — the script queries the private bucket at runtime, reads the `LastModified` timestamp of every CSV, and automatically selects the most recently uploaded file regardless of its name.

**New IAM Permissions Added:**

| Where | What Added | Why |
|---|---|---|
| EC2 IAM Role (`s3readaccess`) | `AmazonSSMManagedInstanceCore` | Allows the SSM Agent on EC2 to receive and execute commands sent by SSM |
| EventBridge Scheduler | `Schedulerrolecustom` (new IAM role) | Allows EventBridge Scheduler to call `ssm:SendCommand` on the EC2 instance |

**Status:** Superseded by Stage 3. EventBridge Scheduler is disabled — event-driven automation is a superior pattern for this use case since it reacts to real data changes rather than running blindly on a timer.

---

### 4.3 Stage 3 — Event-Driven Automation ✅ *(Current)*

**The Goal:** Replace the fixed schedule with an intelligent trigger — the pipeline fires instantly and automatically the moment a new CSV is uploaded to the private bucket. No timer, no polling, no manual action of any kind.

**How It Works:**

```
New CSV uploaded to s3-private-rawdata
        ↓
S3 Event Notification fires automatically
        ↓
AWS Lambda (t20_pipeline_trigger) receives the event
reads exact bucket name + filename from the S3 payload
        ↓
Lambda calls SSM SendCommand:
"run: python3 stage2_pipeline.py 'newfile.csv' on EC2"
        ↓
SSM Agent on EC2 executes the command
stage2_pipeline.py receives the filename via sys.argv[1]
skips auto-detection — uses the exact file Lambda passed
        ↓
Pipeline runs: extract → clean → build HTML → upload
Dashboard updated in s3-public-webhosting
```

**Key code path difference — Stage 2 vs Stage 3:**

```python
def get_csv_key():
    if len(sys.argv) > 1:
        return sys.argv[1]                # Stage 3: Lambda passes exact filename
    return get_latest_file(VAULT_BUCKET)  # Stage 2: auto-detect latest
```

See `lambda_handler.py` for the full Lambda implementation.

**New IAM Permissions Added:**

| Where | What Added | Why |
|---|---|---|
| Lambda execution role (`t20_pipeline_trigger-role-6m1mnkom`) | `AmazonSSMFullAccess` | Allows Lambda to call `ssm:SendCommand` to trigger EC2 |
| Lambda function | S3 trigger (`s3.amazonaws.com`) | Allows S3 to invoke this Lambda when a new object is created |

---

## 5. How the Pipeline Works

**Extract:** `boto3.get_object()` reads the CSV directly from `s3-private-rawdata` into a pandas DataFrame in memory. Authentication is handled entirely by the IAM role attached to the EC2 instance via the Instance Metadata Service (IMDS) — no hardcoded credentials anywhere.

**Transform:** pandas cleans the raw data — fixes column types, strips formatting artifacts (e.g. `"172*"` → `172`), removes duplicate and incomplete rows, and computes the KPIs ready for display.

**Load:** The script builds a complete self-contained HTML page using a Python f-string — embedding inline CSS and a Chart.js bar chart with all data values baked directly into the markup. `boto3.put_object()` uploads it to `s3-public-webhosting` as `index.html`, overwriting the previous version. The live website reflects the new data immediately.

---

## 6. Security Setup

### 6.1 Private Ingestion Bucket (`s3-private-rawdata`)
- **Public Block:** "Block all public access" is explicitly turned on — safeguarding the raw data from external exposure.
- **Data Protection:** Bucket versioning is enabled — ensuring a historical log of all raw CSV modifications is preserved.
- **Access Control:** Read permissions are granted via the managed `AmazonS3ReadOnlyAccess` policy attached to the EC2 IAM role.

### 6.2 Public Hosting Bucket (`s3-public-webhosting`)
- **Public Block:** "Block all public access" is disabled, and Static Website Hosting is enabled to expose the compiled dashboard.
- **Data Protection:** Bucket versioning is enabled to track every deployment of the generated dashboard.
- **Bucket Policy:** A public bucket policy grants `s3:GetObject` to everyone — allowing browsers to render the dashboard while denying all external write operations.

### 6.3 EC2 Authorization (`s3readaccess` IAM Role)
- **Zero-Secret Codebase:** No AWS keys or `.pem` certificates exist anywhere in the script — authentication is handled automatically by the EC2 Instance Metadata Service (IMDS).
- **S3 Read:** `AmazonS3ReadOnlyAccess` — allows the script to fetch raw CSV from the private bucket.
- **S3 Write:** Custom inline policy — grants exclusive `s3:PutObject` rights on `s3-public-webhosting` only.
- **SSM Receive:** `AmazonSSMManagedInstanceCore` — allows the SSM Agent on EC2 to receive and execute remote commands from SSM.

### 6.4 Lambda Execution Role (`t20_pipeline_trigger-role-6m1mnkom`)
- **Trust Policy:** `lambda.amazonaws.com` is the trusted principal — AWS set this automatically when the function was created.
- **SSM Permission:** `AmazonSSMFullAccess` — allows Lambda to call `ssm:SendCommand` targeting the EC2 instance.
- **CloudWatch Logs:** `AWSLambdaBasicExecutionRole` — auto-attached, allows Lambda to write execution logs to CloudWatch.

### 6.5 EventBridge Scheduler Role (`Schedulerrolecustom`) — Stage 2, now disabled
- **Trust Policy:** `scheduler.amazonaws.com` — written manually using custom trust policy because this service is not in the IAM dropdown.
- **Permission Policy:** Custom policy granting `ssm:SendCommand` on the EC2 instance ARN and `AWS-RunShellScript` document ARN.

---

## 7. Setup & Execution

### 7.1 Prerequisites
- An active AWS account with an EC2 instance provisioned.
- Two S3 buckets: `s3-private-rawdata` and `s3-public-webhosting`.
- EC2 IAM Role with `AmazonS3ReadOnlyAccess`, `AmazonSSMManagedInstanceCore`, and a custom inline `s3:PutObject` policy.
- Python 3, `pandas`, and `boto3` installed on the EC2 instance.
- Lambda function `t20_pipeline_trigger` deployed with `AmazonSSMFullAccess` and S3 trigger configured on `s3-private-rawdata`.

### 7.2 Configuration
Update the config section at the top of `stage2_pipeline.py`:

```python
VAULT_BUCKET  = "your_private_bucket_name"
PUBLIC_BUCKET = "your_public_bucket_name"
REPORT_KEY    = "index.html"
# CSV filename resolved automatically — no hardcoding needed
```

Update the instance ID in `lambda_handler.py`:

```python
EC2_INSTANCE_ID = "i-*****************"
```                  

### 7.3 Running the Pipeline

**Stage 1 — manually via SSH:**
```bash
python3 stage1_pipeline.py
```

**Stage 2 — automatically via EventBridge Scheduler (disabled):**
```
EventBridge Scheduler → SSM SendCommand → EC2 runs stage2_3_pipeline.py
```

**Stage 3 — automatically via S3 event (active):**
```
Upload any CSV to s3-private-rawdata
→ S3 fires event → Lambda reads filename → SSM runs stage2_3_pipeline.py
→ Dashboard updates at s3-public-webhosting website URL
```

### 7.4 Monitoring

Every execution can be tracked at two levels:

**SSM Command History** — Systems Manager → Run Command → Command history.
Shows each execution triggered by Lambda, its status (Success / Failed), timestamp, and target instance. Click any row → click Output to see the full terminal output from the EC2 script.

**CloudWatch Logs** — CloudWatch → Log groups → `/aws/lambda/t20_pipeline_trigger`.
Shows Lambda's own execution log — the exact filename it detected from the S3 event payload and the SSM Command ID it sent. If the pipeline fails, the error will appear here first.

| What to check | Where |
|---|---|
| Lambda detected the upload | CloudWatch → `/aws/lambda/t20_pipeline_trigger` |
| EC2 script ran successfully | Systems Manager → Run Command → Command history |
| Dashboard is updated | S3 website URL → check timestamp at bottom of page |

---

## License
This project was built for personal learning purposes.

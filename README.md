# AWS S3 Automated BI Pipeline — Static Web Dashboard

A two-tier cloud data pipeline that takes raw business datasets, processes them with Python and pandas, and publishes a live BI dashboard as a highly available static website — built to learn core AWS storage, security, and automation concepts hands-on.

---

## 1. What This Project Does

- Raw CSV data (cricket batting stats) sits in a private S3 bucket—completely blocked from public access—which acts as our single source of truth.
- A Python script running on an EC2 instance reads the data directly into memory—bypassing local disk storage—where it cleans the records and calculates key metrics using pandas.
- The script generates a styled HTML report with KPI cards and a chart — and uploads it to a second, public S3 bucket.
- This secondary bucket is configured for static website hosting—meaning anyone with the public URL can instantly view the dashboard, which now updates automatically on a schedule without any manual SSH intervention.

---

## 2. Project Stages

### 2.1 Stage 1 — Manual Pipeline ✅
**Overview:** The foundational architecture is built entirely around manual execution to master baseline cloud infrastructure, data manipulation, and explicit permission mapping.

**Infrastructure Setup:** Both S3 buckets are provisioned manually via the AWS Console, and an explicit IAM role is attached to the EC2 instance to grant secure data access.

**Pipeline Execution:** The ETL lifecycle is triggered entirely by hand—requiring an active SSH connection to the EC2 instance to execute the Python script (`stage1_pipeline.py`).

**Data Refresh:** The static website remains fixed until a developer manually runs the script—making this manual step the clear problem statement that drives the need for future automation.

---

### 2.2 Stage 2 — Scheduled Automation ✅
**The Goal:** Eliminate the need for manual SSH intervention by transitioning to a hands-off, time-based schedule using EventBridge Scheduler.

**How It Works:** AWS EventBridge Scheduler fires on a fixed cadence and calls the AWS Systems Manager (SSM) `SendCommand` API, which instructs the SSM Agent running on the EC2 instance to execute `stage2_pipeline.py` — no SSH connection, no manual trigger, no Lambda required.

**Dynamic File Resolution:** Stage 1 hardcoded the CSV filename. Stage 2 introduces `get_latest_file()` — the script now queries the private bucket at runtime, reads the `LastModified` timestamp of every CSV present, and automatically selects the most recently uploaded file. This means the pipeline works correctly regardless of what the uploaded file is named.

**New IAM Permissions Added:**

| Where | What Added | Why |
|---|---|---|
| EC2 IAM Role (`s3readaccess`) | `AmazonSSMManagedInstanceCore` | Allows the SSM Agent on EC2 to receive and execute commands sent by SSM |
| EventBridge Scheduler | `Schedulerrolecustom` (new IAM role) | Allows EventBridge Scheduler to call `ssm:SendCommand` on the EC2 instance |

**Schedulerrolecustom — permission policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:us-east-1:YOUR_ACCOUNT_ID:instance/YOUR_INSTANCE_ID",
        "arn:aws:ssm:us-east-1::document/AWS-RunShellScript"
      ]
    }
  ]
}
```

**Schedulerrolecustom — trust policy** (custom, because `scheduler.amazonaws.com` is not in the IAM dropdown):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "scheduler.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Code change — `stage2_pipeline.py`:** The only code difference from Stage 1 is the addition of `get_latest_file()` and `get_csv_key()`. All cleaning, report generation, and upload logic is unchanged.

```python
# replaces the hardcoded CSV_KEY = "t20.csv" from Stage 1

def get_latest_file(bucket):
    # lists all CSVs in the private bucket and returns
    # the filename with the most recent LastModified timestamp
    response = s3.list_objects_v2(Bucket=bucket)
    csv_files = [obj for obj in response["Contents"]
                 if obj["Key"].endswith(".csv")]
    return max(csv_files, key=lambda obj: obj["LastModified"])["Key"]

def get_csv_key():
    if len(sys.argv) > 1:
        return sys.argv[1]           # Stage 3: Lambda passes exact filename
    return get_latest_file(VAULT_BUCKET)  # Stage 2: auto-detect latest
```

---

### 2.3 Stage 3 — Event-Driven Automation *(planned)*
An S3 Event Notification on the private bucket will fire the instant a new CSV is uploaded. A small Lambda function will act as a relay — reading the exact filename from the S3 event payload and passing it to the same EC2 script via SSM, so the dashboard refreshes immediately rather than waiting for the next scheduled run.

---

## 3. How the Pipeline Works

**Extract:** The Python script invokes `boto3.get_object()` to read the target raw CSV file directly from the private bucket — `s3-private-rawdata` — into memory as a pandas DataFrame. This communication relies entirely on the IAM role attached to the EC2 instance, removing any need for hardcoded credentials.

**Transform:** The script uses pandas to clean and process the raw data. It automatically formats the columns, removes invalid characters, filters out empty rows, and calculates the final batting metrics (KPIs) so they are ready for display.

**Load:** The script converts those final metrics into a simple HTML dashboard. It then uses `boto3.put_object()` to upload this final `index.html` file directly to the public S3 bucket, which instantly updates the live website.

---

## 4. Security Setup

### 4.1 Private Ingestion Bucket (`s3-private-rawdata`)
- **Public Block:** "Block all public access" is explicitly turned on — safeguarding the raw data from external exposure.
- **Data Protection:** Bucket versioning is enabled — ensuring a historical log of all raw CSV modifications is preserved.
- **Access Control:** Read permissions are granted via an IAM policy utilizing the managed `AmazonS3ReadOnlyAccess` permission set — allowing the EC2 instance to securely fetch incoming data.

### 4.2 Public Hosting Bucket (`s3-public-webhosting`)
- **Public Block:** "Block all public access" is disabled, and Static Website Hosting is enabled to expose the compiled dashboard.
- **Data Protection:** Bucket versioning is turned on to track deployments of the generated dashboard.
- **Bucket Policy:** A public bucket policy is applied to universally grant `s3:GetObject` permissions to everyone — allowing web browsers to render the dashboard while completely denying external `s3:PutObject` requests.

### 4.3 EC2 Authorization & Cross-Bucket Security
- **Zero-Secret Codebase:** No AWS access keys, secret keys, or `.pem` certificates exist anywhere inside the script — all resource authentication is managed automatically via the EC2 Instance Metadata Service (IMDS).
- **Granular Write Access:** A custom IAM inline policy is attached directly to the EC2 instance's IAM Role — explicitly granting it exclusive `s3:PutObject` rights over the `s3-public-webhosting` bucket.
- **SSM Access (Stage 2):** `AmazonSSMManagedInstanceCore` is added to the EC2 IAM role — allowing the SSM Agent on the instance to receive remote commands from EventBridge Scheduler via SSM.

---

## 5. Setup & Execution

### 5.1 Prerequisites
- An active AWS account with an EC2 instance provisioned.
- Two custom S3 buckets created: `s3-private-rawdata` and `s3-public-webhosting`.
- An IAM Role attached to the EC2 instance configured with `AmazonS3ReadOnlyAccess`, `AmazonSSMManagedInstanceCore`, and a custom inline write policy.
- Python 3 along with the `pandas` and `boto3` libraries installed on the EC2 server.

### 5.2 Configuration
Update the configuration constants at the top of `stage2_pipeline.py`:

```python
VAULT_BUCKET  = "s3-private-rawdata"
PUBLIC_BUCKET = "s3-public-webhosting"
REPORT_KEY    = "index.html"
# CSV filename is resolved automatically — no hardcoding needed
```

### 5.3 Running the Pipeline

**Stage 1 — manually via SSH:**
```bash
python3 stage1_pipeline.py
```

**Stage 2 — automatically via EventBridge Scheduler:**
EventBridge Scheduler fires on the configured cadence → calls SSM `SendCommand` → SSM Agent on EC2 executes:
```bash
cd /home/ec2-user && python3 stage2_pipeline.py
```
No SSH required. Monitor execution in: **Systems Manager → Run Command → Command history**.

---

## License
This project was built for personal learning purposes.

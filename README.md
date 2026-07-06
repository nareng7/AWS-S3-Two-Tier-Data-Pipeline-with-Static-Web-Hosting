# AWS S3 Automated BI Pipeline — Static Web Dashboard

A two-tier cloud data pipeline that takes raw business datasets, processes them with Python and pandas, and publishes a live BI dashboard as a highly available  static website — built to learn core AWS storage, security, and automation concepts hands-on.

# What This Project Does

☞ Raw CSV data (cricket batting stats) sits in a private S3 bucket—completely blocked from public access—which acts as our single source of truth.

☞ A Python script running on an EC2 instance reads the data directly into memory—bypassing local disk storage—where it cleans the records and calculates key metrics using pandas.

☞ The script generates a styled HTML report with KPI cards and a chart — and uploads it to a second, public S3 bucket.

☞ This secondary bucket is configured for static website hosting—meaning anyone with the public URL can instantly view the dashboard, which updates dynamically whenever the script is manually executed.

# Architecture

<img width="1774" height="887" alt="ChatGPT Image Jul 6, 2026, 11_31_51 AM" src="https://github.com/user-attachments/assets/4eb05f1a-e7c5-44e1-b06f-c8911127b261" />


**Project stages - Stage 1 Manual Pipeline (Current)**

**Overview:** The foundational architecture is built entirely around manual execution to master baseline cloud infrastructure, data manipulation, and explicit permission mapping.

**Infrastructure Setup:** Both S3 buckets are provisioned manually via the AWS Console, and an explicit IAM role is attached to the EC2 instance to grant secure data access.

**Pipeline Execution:** The ETL lifecycle is triggered entirely by hand—requiring an active SSH connection to the EC2 instance to execute the Python script (stage1_pipeline.py).

**Data Refresh:** The static website remains fixed until a developer manually runs the script—making this manual step the clear problem statement that drives the need for future automation.

**Stage 2 — Scheduled Automation**

**The Goal:** Eliminating the need for manual SSH intervention by transitioning to a hands-off, time-based schedule using Event-Bridge Scheduler.

# How the Stage 1 Pipeline Works

**Extract:** The Python script invokes boto3.get_object() to read the target raw CSV file directly from the private bucket—s3-private-rawdata—into memory as a pandas DataFrame. This communication relies entirely on the IAM role attached to the EC2 instance, removing any need for hardcoded credentials.

**Transform:** The script uses the pandas library to clean and process the raw data. It automatically formats the columns, removes invalid characters, filters out empty rows, and calculates the final batting metrics (KPIs) so they are ready for display.

**Load:** The script converts those final metrics into a simple HTML dashboard. It then uses boto3.put_object() to upload this final index.html file directly to your public S3 bucket, which instantly updates the live website.

# Security Setup (Stage 1)

**☞ Private Ingestion Bucket (s3-private-rawdata)**

**Public Block:** "Block all public access" is explicitly turned on—safeguarding the raw data from external exposure.

**Data Protection:** Bucket versioning is enabled—ensuring a historical log of all raw CSV modifications is preserved.

**Access Control:** Read permissions are granted via an IAM policy utilizing the managed AmazonS3ReadOnlyAccess permission set—allowing the EC2 instance to securely fetch incoming data.

**☞ Public Hosting Bucket (s3-public-webhosting)**

**Public Block:** "Block all public access" is disabled, and Static Website Hosting is enabled to expose the compiled dashboard.

**Data Protection:** Bucket versioning is turned on to track deployments of the generated dashboard.

**Bucket Policy:** A public bucket policy is applied to universally grant s3:GetObject permissions to everyone—allowing web browsers to render the dashboard while completely denying external s3:PutObject requests.

**☞ EC2 Authorization & Cross-Bucket Security**

**Zero-Secret Codebase:** No AWS access keys, secret keys, or .pem certificates exist anywhere inside the script—all resource authentication is managed automatically via the EC2 Instance Metadata Service (IMDS).

**Granular Write Access:** To allow the EC2 instance to publish the dashboard, a custom IAM inline policy is attached directly to the EC2 instance's IAM Role—explicitly granting it exclusive s3:PutObject rights over the s3-public-webhosting bucket.

<img width="2848" height="1304" alt="Screenshot 2026-07-06 at 10 47 20 AM" src="https://github.com/user-attachments/assets/e1322d6e-e0bd-458c-9d1e-c74710fb548f" />


# Setup & Execution (Stage 1)

**Prerequisites**

☞ An active AWS account with an EC2 instance provisioned.

☞ Two custom S3 buckets created: s3-private-rawdata and s3-public-webhosting.

☞ An IAM Role attached to the EC2 instance configured with **AmazonS3ReadOnlyAccess** and your **custom inline write policy**.

☞ Python 3 along with the pandas and boto3 libraries installed on the EC2 server.

**Configuration**

Before executing the pipeline, update the configuration constants at the top of your stage1_pipeline.py script to map to your specific AWS resources:

# stage1_pipeline.py - Configuration Section

**RAW_DATA_BUCKET**  = "your-private-bucket-name"

**WEB_INDEX_BUCKET** = "your-public-bucket-name"

**INPUT_CSV_FILE**   = "your-file-name.csv"  # The targeted raw file inside your private bucket.

**☞ Running the Pipeline Manually**

To execute the Stage 1 ETL workflow, establish an SSH connection to your EC2 instance and run the script manually via the terminal:

**Navigate to your project directory and execute the pipeline**

python3 stage1_pipeline.py

<img width="2880" height="620" alt="Screenshot 2026-07-06 at 10 58 08 AM" src="https://github.com/user-attachments/assets/825c5a2e-70ce-4958-9981-089d5cad6092" />



Once the execution log outputs a successful upload confirmation, open your browser and navigate to your S3 static website endpoint URL to view your updated dashboard.


# License
**This project was built for personal learning purposes**

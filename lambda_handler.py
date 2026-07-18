"""
lambda_handler.py
────────────────────────────────────────────────────────────
T20 Pipeline — Stage 3: Event-Driven Trigger (Lambda relay)

WHAT THIS FILE IS:
  A brand new, separate file — NOT a change to stage2_pipeline.py.
  This is the ONLY new code needed to go from Stage 2 to Stage 3.

WHAT IT DOES:
  S3 fires an event the instant a new CSV lands in Bucket 1.
  That event triggers this Lambda function. The event "payload"
  (the JSON AWS sends) already contains the exact bucket name
  and exact filename that was just uploaded — no guessing, no
  listing the bucket needed here.

  This function reads that filename out of the payload, then
  calls AWS Systems Manager (SSM) to remotely run the EC2
  script — passing the exact filename as a command-line
  argument. That argument is what stage2_pipeline.py's
  get_csv_key() function picks up via sys.argv.

DEPLOY:
  AWS Console → Lambda → Create function → Python runtime
  → paste this code → set EC2_INSTANCE_ID below
  → attach AmazonSSMFullAccess (or a tighter custom policy)
    to this Lambda's execution role
  → S3 Bucket 1 → Properties → Event notifications
    → Create event notification → All object create events
    → Destination: this Lambda function
"""

import boto3
import urllib.parse

# ── CONFIG — change this one value ─────────────────────────────────────────
EC2_INSTANCE_ID = "i-xxxxxxxxxxxxxxxxx"   # find it: EC2 console → Instances → Instance ID


def lambda_handler(event, context):
    # ── extract bucket + filename from the S3 event payload ────────────────
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]

    # S3 event keys can be URL-encoded (spaces become "+" etc.)
    # unquote_plus decodes it back to the real filename
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

    print(f"New file detected: s3://{bucket}/{key}")

    # ── tell SSM to run the existing script on EC2, passing the filename ───
    ssm = boto3.client("ssm")
    response = ssm.send_command(
        InstanceIds=[EC2_INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={
            "commands": [
                f"cd /home/ec2-user && python3 stage2_pipeline.py '{key}'"
            ]
        },
    )

    print(f"SSM command sent: {response['Command']['CommandId']}")
    return response

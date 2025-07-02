# ⚙️ Infrastructure Overview

This document outlines the serverless infrastructure powering the **Mixer – Serverless Narration & Music Audio Mixer**. It leverages AWS services orchestrated via Infrastructure as Code (IaC) using AWS CloudFormation for easy deployment and maintenance.

---

## 🛠 Infrastructure Components

The Mixer application is composed of three main CloudFormation stacks:

### 1. [MixerInfraStack](../IaC/MixerInfraStack.yml)

**Purpose:**

* Sets up foundational infrastructure including AWS ECR for Docker images, AWS CodeBuild for continuous integration, and AWS CodePipeline for CI/CD workflows.

**Key Resources:**

* **ECR Repository:** Stores Lambda Docker images.
* **S3 Bucket:** `mixeroutputbucket` for storing audio output.
* **CodeBuild Project:** Builds Docker images from source.
* **CodePipeline:** Automates deployments from GitHub source code.

---

### 2. [PollySpeechAPI Stack](../IaC/PollySpeechAPI.yml)

**Purpose:**

* Exposes Amazon Polly through a Lambda function and HTTP API Gateway for speech synthesis.

**Key Resources:**

* **Lambda Function** (Python 3.12) for text processing & Amazon Polly integration.
* **API Gateway HTTP API** to invoke the Lambda function securely.
* IAM Roles configured with least privilege access.

---

### 3. [MixerAppStack](../IaC/MixerAppStack.yml)

**Purpose:**

* Deploys the Mixer Lambda function (as a Docker container) behind an HTTP API Gateway.

**Key Resources:**

* **Lambda Container:** Runs audio mixing and narration logic.
* **API Gateway:** Exposes the Lambda securely over HTTP.
* **IAM Roles:** Configured to securely access S3, ECR, and external Polly API.

---

4. **[SanitationStack](../IaC/SanitationStack.yml)**

**Purpose:**

Automates the cleanup and lifecycle management of S3 objects and ECR images to reduce storage costs and keep your environment clean.

**Key Resources:**

- **Cleanup Lambda Functions:**  
  - *S3CleanupFunction*: Deletes old files from one or more S3 buckets based on age and (optionally) prefix.
  - *ECRCleanupFunction*: Removes old image tags from one or more ECR repositories (skips `latest` tag by default).
- **IAM Role:**  
  - Least-privilege permissions for S3, ECR, and CloudWatch Logs access by the Lambda functions.
- **EventBridge Schedule Rule:**  
  - Triggers the cleanup Lambda functions on a set schedule (e.g., every 10 days, configurable in the template).
- **Parameterization:**  
  - Pass up to 3 S3 buckets and 3 ECR repositories as parameters for full reusability.

**Deployment:**  
Deploy `SanitationStack.yml` via CloudFormation.  
Configure which buckets and repositories to manage using template parameters.

**Example Use Cases:**  
- Automatically delete narration chunks or mixed audio files older than 10 days.
- Periodically prune ECR images to keep only the most recent/required tags.
  
---


## 📁 Repository Structure

```
Mixer/
├── Dockerfile
├── app.py
├── buildspec.yml
├── requirements.txt
├── README.md
├── LICENSE
├── IaC/
│   ├── MixerAppStack.yml
│   ├── MixerInfraStack.yml
│   ├── PollySpeechAPI.yml
│   └── SanitationStack.yml
└── docs/
    ├── Fullinfra.png
    └── infrastructure.md   # (this document)

```

---

## 🚀 Deploying the Infrastructure

Deploy stacks in the following order:

1. **MixerInfraStack** (ECR, S3, CI/CD)
2. **PollySpeechAPI** (Lambda + Polly API Gateway)
3. **MixerAppStack** (Mixer Lambda, depends on resources from stacks above)

This ordering is critical because the MixerAppStack depends on resources created by the previous two stacks, specifically the ECR repository created by MixerInfraStack. The ECR repository is initially empty, and it requires a first image built and pushed by the CodeBuild and CodePipeline resources defined in MixerInfraStack before the MixerAppStack Lambda function can reference this image during deployment. Attempting to deploy the stacks out of this order will cause the deployment to fail due to a non-existent or missing container image in ECR.

Use AWS CloudFormation through the AWS console or CLI:

```sh
aws cloudformation deploy \
    --template-file MixerInfraStack.yml \
    --stack-name MixerInfraStack
```

Repeat for each stack, providing the necessary parameter values.

---

## 🔗 Useful Links

* [Main README](../README.md)
* [Polly Speech API Stack](../IaC/PollySpeechAPI.yml)
* [Mixer Infrastructure Stack](../IaC/MixerInfraStack.yml)
* [Mixer Application Stack](../IaC/MixerAppStack.yml)
* [SanitationStack](../IaC/SanitationStack.yml)
---

🎯 **Goal:** Enable simple, repeatable, secure, and scalable serverless audio processing on AWS.

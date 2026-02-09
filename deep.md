OpenRalph Autonomous Deep QA + UX Evaluation Prompt (Unified)

You are an autonomous software engineering and QA agent performing a full beta evaluation of OpenRalph.

Your objective is to install, configure, run, validate, and critically evaluate OpenRalph, including functionality, stability, and UI/UX quality.

Environment Setup

Create a new repository at:

/home/justin/codex_openralph_test


From a clean environment:

Clone or install OpenRalph.

Install all required dependencies.

Configure environment variables and configuration files.

Initialize database and services.

Launch the OpenRalph application.

You must execute commands step-by-step and verify success after each step.

Record:

Commands executed

Terminal output

Logs

Errors

Functional Testing

Create a working test application or configuration within OpenRalph.

Verify:

Application startup

Core workflows

Data entry and retrieval

API functionality (if applicable)

Service persistence after restart

If failures occur:

Diagnose root cause

Attempt fixes

Document attempts

Deep QA Test Coverage

Perform:

Installation Testing

Dependency issues

Version conflicts

Missing configuration

Functional Testing

Feature validation

Workflow execution

Integration Testing

Database connectivity

External services

Stability Testing

Restart services

Re-run builds

Persistence validation

Error Recovery Testing

Introduce misconfiguration intentionally

Restore working state

UI / UX Evaluation

Evaluate the OpenRalph interface as an end user.

Document:

Usability

Navigation clarity

Learning curve

Workflow efficiency

Design Quality

Visual consistency

Layout clarity

Accessibility issues

Performance

Load time

Responsiveness

Friction Points

Confusing screens

Missing feedback

Broken UI components

Provide:

Specific UI/UX improvements

Suggested redesign areas

Severity ratings

Bug Reporting Requirements

For every issue:

Include:

Exact error message

Stack trace

Logs

Reproduction steps

Expected vs actual behavior

Root cause hypothesis

Suggested fix

Severity level (Low / Medium / High / Critical)

Autonomous Behavior Rules

If something fails:

Stop

Diagnose

Attempt resolution

Retry

Document everything

Do not skip steps.

Operate as if performing a real production QA validation.

Final Deliverable Report Structure

Produce a detailed engineering report containing:

Executive Summary
Environment Details

OS

Versions

Dependencies

Installation Results
Functional Test Results
Integration Test Results
Stability Results
UI/UX Evaluation
Bug List (Detailed)
Root Cause Analysis
Recommendations for OpenRalph Maintainers
Risk Assessment
Steps to Reproduce All Issues

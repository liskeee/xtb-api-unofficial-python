# Security Policy

## Reporting a vulnerability

If you discover a security issue in xtb-api-python, **please do not open a
public GitHub issue.** Instead, email the maintainer at
**ll.lukasz.lis@gmail.com** with the details.

Please include:

- A description of the issue and its impact
- Steps to reproduce, if possible
- The version of xtb-api-python affected

You should receive an initial response within 7 days. Once the issue is
confirmed and a fix is prepared, the maintainer will coordinate disclosure
with you.

## Supported versions

Only the latest minor release line receives security fixes:

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| < 0.5   | :x:                |

## Scope

This project is an **unofficial** client for XTB's xStation5 platform. Bugs
in XTB's own infrastructure are out of scope — report those directly to XTB.

Credential handling, TGT/JWT persistence, and TOTP secret storage are in scope.

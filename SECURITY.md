# Security and data boundaries

The default launcher binds to loopback and runs only synthetic clinical data. It is not configured for public internet access, hospital single sign-on or production clinical use. Do not expose its ports through a public tunnel.

Report a vulnerability through the repository owner's private contact or GitHub's private reporting channel if available. Do not include secrets, patient information, live session cookies or identifiable reproduction files in public issues. Use synthetic reproductions and describe the affected code path.

## Maintained boundaries

- Clinical review remains authoritative; model output is a candidate requiring human action.
- Knowledge sources remain separate from patient records.
- Prescription collections retain their own identity and revision scope.
- Writable artifacts must stay inside ignored run directories.
- The public repository excludes credentials, source clinical exports, databases, derived private reports, literature collections and model weights.
- Authentication stores, account recovery and real-model integrations require independent deployment review before real-data use.

The release scanner detects specific prohibited files and patterns. It does not establish de-identification, clinical validity or the absence of every possible sensitive string. Review both file provenance and the staged diff before publishing.

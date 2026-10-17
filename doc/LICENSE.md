# License

This project is licensed under the MIT License.

The canonical license text now lives in the [`LICENSE`](../LICENSE) file at the
repository root. Please refer to it for the full terms.

Copyright (c) 2026 [Agent-Lab Developers](ACKNOWLEDGEMENT.md)

## Open source commitment

Agent-Lab is developed in the open on GitHub under the MIT License — free to use,
study, modify and redistribute, for any purpose. The framework's generic
capabilities live in this public repository, its roadmap and issues are visible to
everyone, and upstream contributions following the [Developer's
Guide](DEV_GUIDE.md) are welcome.

## Responsible development

Security is practiced, not promised: dependencies are updated automatically via
weekly [Dependabot](../.github/dependabot.yml) runs, runtime secrets are kept in
[Vault](VAULT.md) instead of the repository, and the reference deployments
provision [Keycloak](KEYCLOAK.md) for authentication as a first-class component.
Vulnerabilities are handled responsibly — please do not open public issues for
them; follow the coordinated disclosure process in
[SECURITY.md](../SECURITY.md).

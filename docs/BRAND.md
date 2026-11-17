# PrivyFlow — Brand and Product Messaging

## 1. Brand foundation

- **Name:** PrivyFlow
- **Category:** Privacy engine / privacy infrastructure
- **Positioning:** A developer-focused privacy engine that sanitizes sensitive text and supports controlled restoration through independently deployable services.
- **Core promise:** Help applications control sensitive information before it is shared with other systems, while enabling authorized restoration when required.

## 2. Tagline options

- Privacy Infrastructure for Applications
- Sanitize Sensitive Data. Restore with Control.
- Protect Sensitive Text at the Application Boundary.

## 3. Messaging pillars

| Pillar | Message |
|---|---|
| Privacy by design | Sensitive-data protection is built into application workflows. |
| Policy-driven sanitization | Teams define which sensitive categories are transformed and how. |
| Controlled restoration | Original values are restored only through an authorized, scoped process. |
| Secure mapping management | Reversible mappings are encrypted and governed by expiry and access controls. |
| Developer-first architecture | Two independently deployable services integrate through documented APIs. |

## 4. Audience

- Developers building applications that process sensitive text.
- Enterprise architecture and platform engineering teams.
- Security, privacy, and governance stakeholders.
- SaaS companies that need to minimize sensitive-data exposure to downstream systems.

## 5. Voice and tone

- Clear, precise, technically credible, and developer-friendly.
- Confident about controls, careful about guarantees.
- Explain boundaries, assumptions, and trade-offs.
- Avoid fear-based messaging and unsupported compliance claims.
- Plain business English in US spelling. Short labels, no unnecessary jargon, and no exclamation marks.

## 6. Product terminology

| Term | Meaning |
|---|---|
| Sanitization Service | Detects configured sensitive entities, applies policies, masks values, and stores encrypted mappings. |
| De-sanitization Service | Restores authorized placeholders using mappings obtained through the Sanitization Service internal API. |
| Sanitization | Replacing selected sensitive values with placeholders. |
| De-sanitization | Replacing authorized placeholders with their original values. |
| Placeholder | A generated marker representing a sensitive value, such as `[PERSON_001]`. |
| Restoration credential/reference | High-entropy secret/reference used as one input to a controlled restoration flow. |
| Mapping vault | Encrypted storage for reversible placeholder-to-value mappings. |
| Tenant scope | Boundary that prevents one customer context from accessing another. |

## 7. Claims to avoid

- Do not claim “100% anonymization,” “zero risk,” or “impossible to re-identify.”
- Do not claim guaranteed detection of every sensitive entity.
- Do not claim regulatory compliance or certification unless independently established.
- Do not imply that encryption alone provides complete security.
- Do not imply that possession of a restoration credential alone grants authorization.

## 8. Short product description

PrivyFlow is a developer-focused privacy engine with two independent services. The Sanitization Service detects and replaces configured sensitive information while securely retaining encrypted mappings. The De-sanitization Service restores original values only through an authenticated, authorized, and scoped workflow.

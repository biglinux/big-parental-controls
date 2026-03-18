# Data Protection Impact Assessment (DPIA)

**Application:** Big Parental Controls
**Version:** 1.0
**Date:** 2026-03-17
**Assessor:** BigLinux Development Team

## 1. Nature of Processing

Big Parental Controls monitors computer usage by minors under parental
supervision. The system collects:

- **Process names** of running applications (checked every 60 seconds)
- **Session times** (login/logout from system logs)
- **Duration of use** per application per day
- **Age group** of the supervised user (child/teen/adult — not exact age)

## 2. Scope

- **Data subjects:** Minors designated as "supervised" by the administrator
- **Geographic scope:** Primarily Brazil (ECA Digital) and EU (GDPR/DSA)
- **Processing location:** Exclusively local — the device running the software
- **Data volume:** Approximately 1-2 KB per user per day (JSON files)
- **Retention:** 30 days, with automatic deletion of older records

## 3. Context

- **Relationship:** Parent/guardian managing a child's computer access
- **Expectation:** Users expect parental control software to monitor usage
- **Control:** Administrator (parent) has full control over enabling/disabling
- **Prior experience:** Similar to existing tools (macOS Screen Time, Windows
  Family Safety, GNOME Malcontent)

## 4. Purpose

The sole purpose of data processing is **child safety** in the digital
environment, as mandated by:

- **ECA Digital (Law 15.211/2025, Art. 17, XII)** — parental control tools
- **ECA Digital (Art. 18)** — usage reports for parents
- **LGPD (Art. 14)** — protection of children's data with parental consent
- **GDPR (Art. 8)** — conditions for child consent in information services
- **UK Children's Code (Standard 14)** — parental controls

## 5. Risk Assessment

### 5.1 Risks to Data Subjects

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Unauthorized access to usage data | Low | Medium | Data stored root:root 700, D-Bus policy restricts access |
| Excessive surveillance by parent | Medium | Medium | Supervised user is informed via tray indicator |
| Data breach via network | Very Low | High | No network transmission — local only |
| Data retained beyond necessity | Low | Low | Automatic 30-day cleanup |
| Child not informed about monitoring | Low | Medium | Mandatory tray indicator shows monitoring status |

### 5.2 Residual Risk

**LOW** — All identified risks have adequate mitigations in place.

## 6. Compliance Measures

### 6.1 Lawfulness (GDPR Art. 6/Art. 8, LGPD Art. 14)
- Monitoring requires explicit informed consent via dialog
- Consent dialog covers all GDPR Art. 13 information requirements
- Administrator (parent/guardian) provides consent

### 6.2 Data Minimization (GDPR Art. 5.1(c), LGPD Art. 14)
- Only process names collected (no command-line arguments)
- No file contents, keystrokes, or screen captures
- No browsing history or network traffic analysis
- Age verification uses ranges, not exact dates of birth

### 6.3 Purpose Limitation (GDPR Art. 5.1(b))
- Data used exclusively for parental safety monitoring
- No profiling, advertising, or third-party sharing
- No telemetry or analytics

### 6.4 Storage Limitation (GDPR Art. 5.1(e))
- 30-day automatic retention with cleanup
- Administrator can delete all data at any time

### 6.5 Integrity and Confidentiality (GDPR Art. 5.1(f))
- Data directory: `/var/lib/big-parental-controls/activity/` (root:root 700)
- Atomic JSON writes prevent corruption
- D-Bus policy restricts Enable/Disable to wheel group
- Read-only methods accessible to all (for supervised user transparency)

### 6.6 Data Subject Rights

| Right | Implementation |
|-------|---------------|
| **Access** (GDPR Art. 15, LGPD Art. 18) | "View my data" in tray indicator for supervised user |
| **Erasure** (GDPR Art. 17, LGPD Art. 18) | "Delete Activity Data" button with confirmation dialog |
| **Portability** (GDPR Art. 20) | "Export Activity Data" as JSON file |
| **Objection** (LGPD Art. 18) | Admin can disable monitoring at any time |
| **Information** (GDPR Art. 13-14) | Consent dialog + compliance banners in UI |

### 6.7 Transparency
- Supervised user is always informed via system tray indicator
- Consent dialog shows full data processing details
- Legal framework references displayed in the application
- Source code is open and auditable

## 7. Consultation

This DPIA was prepared considering:
- Brazilian ECA Digital (Law 15.211/2025)
- Brazilian LGPD (Law 13.709/2018)
- EU General Data Protection Regulation (2016/679)
- EU Digital Services Act (2022/2065)
- UK Age Appropriate Design Code (Children's Code)

## 8. Conclusion

The processing of personal data by Big Parental Controls presents a **low
residual risk** to the rights and freedoms of data subjects. The application
implements privacy by design and by default, with local-only data storage,
automatic retention limits, informed consent, transparency to the supervised
user, and full data subject rights (access, erasure, portability).

**Note:** GDPR Art. 2.2(c) potentially exempts purely domestic/household
use. However, this DPIA is maintained to demonstrate good faith and to
cover potential institutional use (schools, libraries).

---

*This document should be reviewed annually or when significant changes
are made to data processing activities.*

# BopClients Brand Assets

This directory contains the official BopClients visual brand assets integrated in P30.3.

## Official Asset Status
- **OFFICIAL LOGO FILE PRESENT**: `True` (`apps/web/public/brand/BopClients.png`)
- **DERIVED WORDMARK PRESENT**: `True` (`apps/web/public/brand/bop-clients-wordmark.png`)
- **DERIVED COLLAPSED MARK PRESENT**: `True` (`apps/web/public/brand/bop-clients-mark.png`)
- **DERIVED ICON PRESENT**: `True` (`apps/web/public/brand/bop-clients-icon.png`)
- **FABRICATED BRAND MARK PRESENT**: `False`
- **OFFICIAL GOLD HEX VERIFIED**: `#C5A059` (Matches official logo circular ring mark)

## Public Assets Structure
- `BopClients.png`: Canonical 1:1 user-provided PNG asset (1254x1254).
- `bop-clients-logo.png`: Public copy of the canonical user-provided asset.
- `bop-clients-wordmark.png`: Exact artwork crop for desktop navigation and headers.
- `bop-clients-mark.png`: Exact artwork crop for collapsed sidebar navigation.
- `bop-clients-icon.png`: Derived high-resolution favicon and app icon.

The `BrandLogo` component automatically renders the official logo assets. In case of asset load failure, it falls back to the clean typographic fallback.
No fabricated SVG icons or geometric nodes are permitted.

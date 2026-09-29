<!-- Thank you for submitting an Add-on to the LocalBib Marketplace. -->

## Checklist

- [ ] `index.json` lists my Add-on under `addons`, with a new entry prepended
      to its `versions` (newest first)
- [ ] `license` is a non-empty SPDX expression and matches my Add-on's
      `plugin.json`
- [ ] `homepage` links to my Add-on's public source repository
- [ ] The version's `artifacts[0].url` points at a public GitHub Release
      asset — the Zip `localbib-addon build` produced
- [ ] `artifacts[0].sha256` and `artifacts[0].size` are the checksum file
      `localbib-addon build` wrote next to the Zip — never typed by hand
- [ ] `localbib-addon check` passes locally on my Bundle folder
- [ ] This pull request touches only my own entry in `index.json`

## What "third-party" means

Every Add-on submitted through this repository is shown in the Marketplace
as **Drittanbieter** (third-party), never as **Offiziell**. The CI on this
pull request checks the *shape* of your submission — schema, a reachable and
checksummed download, a Manifest that matches what you declared, a Bundle
that passes `localbib-addon check` — never its behaviour, how it uses its
declared Berechtigungen, or its trustworthiness. An Add-on runs in the same
process with all of LocalBib's own rights on the user's machine; installing
one is a decision the user makes about *you*, not a claim this review
verifies.

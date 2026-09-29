# LocalBib Marketplace-Index

This repository is the index of the LocalBib Marketplace. LocalBib fetches
`index.json` from the `main` branch and shows every entry as a card; the
images under `assets/<id>/` are loaded relative to this repository.

## Format

```json
{
  "updated": "2026-09-25T00:00:00Z",
  "addons": [
    {
      "id": "example",
      "name": "Example",
      "tagline": "One line, up to 80 characters.",
      "description": "Markdown.",
      "author": "Someone",
      "license": "MIT",
      "homepage": "https://github.com/someone/localbib-example",
      "trust": "third-party",
      "languages": ["en"],
      "tags": [],
      "icon": "assets/example/icon.png",
      "screenshots": ["assets/example/screenshot-1.png"],
      "versions": [
        {
          "version": "1.0.0",
          "api_version": 2,
          "min_core": "0.8.0",
          "released": "2026-09-25",
          "changelog": "First release.",
          "requires_source": false,
          "permissions": ["library.read"],
          "artifacts": [
            {"python": "any", "url": "https://github.com/someone/localbib-example/releases/download/v1.0.0/example-1.0.0.zip", "size": 12345, "sha256": "<64 hex digits>"}
          ]
        }
      ]
    }
  ]
}
```

`trust` is `official` for Add-ons published by the LocalBib project and
`third-party` for everything else. A version's `artifacts` entry is the index
snippet that `localbib-addon build` writes next to the Bundle, with the
download URL of the release asset; never type a checksum by hand.

An entry with `"versions": []` is *announced*: its texts and images are
reviewed and merged first, and its first release is added to it afterwards
(the release snippet needs an entry to land in). LocalBib shows no card for
an announced entry until it has a version.

An artifact's `python` is `any` for a Bundle of pure Python, or the build tag
of the interpreter it was built for (`cp313-win_amd64`) when it carries
compiled libraries in `vendor/`; LocalBib offers such an artifact only to a
core running exactly that interpreter.

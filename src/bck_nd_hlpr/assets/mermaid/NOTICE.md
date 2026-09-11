# Embedded Mermaid renderer

- Upstream: https://github.com/mermaid-js/mermaid
- Version: **11.17.2** (MIT; see the accompanying `LICENSE`).
- Official archive: https://registry.npmjs.org/mermaid/-/mermaid-11.17.2.tgz
- Verified archive SRI: `sha512-V6K3C8EBdEsPFZXSKMJe6ppQOENxuHARr9GvHX4hh47lAbhMRD9qf4oEK7LoaRQxULMa80/qt5gHO73aCleBBg==`
- Original archive member: `package/dist/mermaid.min.js`.
- Original byte count: **3572661**.
- Original SHA-256: `581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8`.

`mermaid.min.js.gz` is the unmodified upstream browser bundle compressed with
gzip (`mtime=0`). Decompression reproduces the original bytes and retains its
bundled notices. Compression also prevents the project scanner from treating
vendor JavaScript as application architecture. Source maps are not shipped.

The Python documentation generator embeds the bundle and MIT license in the
single output HTML. Only HTML raw-text closing tags are escaped at that boundary.
No Node.js, browser executable, package manager, CDN or network connection is
required to generate or open the portal. Drawing requires JavaScript enabled in
the viewer's browser. Upgrading this asset is an explicit maintenance operation,
not a runtime download.

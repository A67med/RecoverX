# RecoverX Windows Quick UI - changes against RecoverX_OneClick_Kali_v0.3

- Source is the complete RecoverX v0.3 Kali package, preserving recovery engines, forensics, case audit, CART selector, tests and historic experiment data.
- Windows-only Quick Recovery page without sidebar or research navigation.
- Quick Recovery strategy dropdown restored: Smart (default), TSK only, PhotoRec only, both, CART-only, and rule-v1-only. Smart still uses CART (rule-v1 fallback) and tries the opposite engine when its first single-engine attempt fails or yields zero outputs.
- Windows native image picker, user-local workspace, auto discovery of 64-bit PhotoRec and TSK windows distributions.
- Windows-safe process cancellation, one-time PowerShell setup and CMD launcher/desktop shortcut.
- Linux block-device capture does not run on Windows; Windows direct device capture is **not implemented**.
- Runtime parity with Windows is not verified here; source tests are possible, Windows binaries are downloaded at the user's first setup.

# Third-party notices

This application includes third-party software. Their licenses and notices are retained in the bundled packages and browser directories.

- pywebview: BSD-3-Clause. https://github.com/r0x0r/pywebview
- pythonnet and clr-loader: MIT. https://github.com/pythonnet/pythonnet
- Microsoft Edge WebView2 Runtime and SDK: Microsoft license terms. https://developer.microsoft.com/microsoft-edge/webview2/
  The runtime is installed and maintained separately by Microsoft's Evergreen installer. Its bootstrapper is bundled after Microsoft Authenticode signature verification.
- bottle: MIT. https://bottlepy.org/
- proxy-tools: BSD-style. https://github.com/jtushman/proxy_tools
- Playwright: Apache-2.0. https://github.com/microsoft/playwright
- Chromium: BSD-style and included third-party licenses. https://www.chromium.org/chromium-projects/
- cryptography: Apache-2.0 / BSD-3-Clause. https://github.com/pyca/cryptography
- requests: Apache-2.0. https://github.com/psf/requests
- icalendar: BSD-2-Clause. https://github.com/collective/icalendar
- recurring-ical-events: LGPL-3.0. https://github.com/niccokunzmann/python-recurring-ical-events
- tzdata: Apache-2.0; underlying timezone data is public domain. https://github.com/python/tzdata
- PyInstaller bootloader: GPL with exception for distributed applications. https://pyinstaller.org/en/stable/license.html

Android application additionally uses:

- Chaquopy: MIT. https://github.com/chaquo/chaquopy
- CPython: Python Software Foundation License. https://docs.python.org/3/license.html
- AndroidX: Apache-2.0. https://source.android.com/docs/setup/about/licenses
- Android System WebView: installed and maintained by the device; Chromium and its third-party notices apply. No separate Chromium binary or Playwright is bundled in the Android APK.
- python-dateutil: Apache-2.0 / BSD-3-Clause. https://github.com/dateutil/dateutil

Android includes only the shared Python dependencies plus the Android runtime; the Windows-only components listed above are not bundled in the APK.

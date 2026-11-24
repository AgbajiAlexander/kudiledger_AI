# KLD-006C3 physical Android validation

Use two consented physical devices, including a low-cost phone, with current Android Chrome and a testing profile. Use synthetic names, credentials and records. Test one device at a time with a fresh demo for each device. Record the exact Git SHA and results in the [device evidence template](android-device-evidence.md).

## Windows USB setup

1. Download the Windows SDK Platform-Tools ZIP from Google. Extract it to a private directory such as `%LOCALAPPDATA%\Android`, so `platform-tools\adb.exe` exists inside it. Use a data-capable USB cable. If Windows cannot see the phone, use its manufacturer's official USB driver. [Platform-Tools](https://developer.android.com/tools/releases/platform-tools) · [ADB and USB debugging setup](https://developer.android.com/tools/adb)
2. Enable Developer options and USB debugging on the phone, leave Wireless debugging off, unlock the phone and approve the USB debugging prompt for the trusted Windows computer. Use the following commands in PowerShell. Verify the version and a single USB row in state `device`. If it is `unauthorized`, unlock the phone and review its prompt. Use `-d` throughout to select the sole USB device.

```powershell
$adb = Join-Path $env:LOCALAPPDATA 'Android\platform-tools\adb.exe'
& $adb version
& $adb devices -l
& $adb -d get-state
& $adb -d shell getprop ro.product.model
& $adb -d shell getprop ro.build.version.release
& $adb -d shell cat /proc/meminfo | Select-String '^MemTotal:'
```

3. In a second PowerShell window at the repository root, use Python 3.13 with the pinned dependencies. Note the numerical port in the printed dashboard URL. Leave the console running.

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m scripts.commissioning_demo
```

4. In the first window, enter the actual printed port and verify that the only listener on it is Windows IPv4 loopback. Then map that port from the USB phone to Windows and verify the mapping.

```powershell
$port = [int](Read-Host 'Port from the synthetic dashboard URL')
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop)
if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') {
    throw 'Expected one Windows listener bound to 127.0.0.1'
}
& $adb -d reverse --no-rebind "tcp:$port" "tcp:$port"
if ($LASTEXITCODE -ne 0) { throw 'ADB reverse failed' }
& $adb -d reverse --list
"http://127.0.0.1:$port/app"
```

5. Open the printed URL in Android Chrome. Keep the app bound to `127.0.0.1`. Avoid LAN listeners, wireless ADB, tunnels and firewall changes. Each demo issues two private invitation files for `commissioning@example.test` and `commissioning-other@example.test`. Open each captured invitation link in Windows browser tabs, set distinct synthetic passwords and sign in to both accounts on the phone in turn. This avoids transferring activation tokens to the phone. Close any tab showing a link. Capture Chrome version from Chrome settings, and record USB reverse and the phone's Wi-Fi/mobile state separately. USB tests do not measure Nigerian carrier latency or public TLS.

## Device exercises

| ID | Steps and expected result |
| --- | --- |
| A1 | In touch mode, traverse all dashboard sections and orient the phone in portrait and landscape. With TalkBack enabled, revisit login, customer search, amount fields, confirmation, error messages, receipt controls and recovery. Check announced names and amounts, reading order, focus after validation/receipt closure, and no clipped controls. |
| A2 | Create synthetic customer Amina Device. Stage a ₦100.01 sale with ₦20.01 paid and reference `DEVICE-SALE-1`. Cancel confirmation first and verify the reference is absent and debt remains ₦0.00. Submit intentionally once. Record repayment `DEVICE-PAY-1` of ₦5.01 and expense `DEVICE-EXP-1` of ₦1.01. On the same Lagos date, reconcile totals ₦100.01 sales, ₦25.02 received, ₦1.01 expenses and ₦74.99 current debt. |
| A3 | Retrieve the sale receipt by reference. Verify ₦100.01, ₦20.01 paid, ₦80.00 due at sale, Lagos timestamp and recorded-payment wording. Open both A4 and narrow print layouts in Android's print service. Inspect page count, width and kobo precision. If an approved printer is available, print to it. Record physical printing separately from preview. |
| A4 | Leave an open receipt and enter `E` in the Windows demo console to expire the sandbox's sessions. Attempt to print or look up the receipt. Expect sign-in to be required and stale details to remain unavailable. Sign back in and repeat after closing a receipt and after a lookup miss. |
| A5 | Under the primary account, stage `DEVICE-NOT-SENT-1` for ₦10.01 on credit. Remove the ADB mapping **before tapping the final confirmation**, verify the mapping is absent, then tap once and observe the failure. Restore the same mapping and check recovery and receipt lookup. Confirm zero new financial effects and debt of ₦74.99. Keep any ambiguous draft on hold. |
| A6 | With the mapping healthy, enter `L` in the demo console. Confirm `DEVICE-LOST-1` for ₦20.01 on credit. The server commits then sends a synthetic HTTP 503. Do not submit again. Background Chrome and reopen it, then refresh or expire the session with `E` and sign in again. Look up the original pending reference under Recovery, open the verified receipt and reconcile exactly one sale, ₦120.02 daily sales and ₦95.00 current debt. This models the lost acknowledgement independently of USB timing. |
| A7 | Before resolving the A6 reference, sign out and log into the second business. Verify that its recovery list has no primary-business reference and receipt lookup by the known reference reveals no details. Sign back in to the primary business, verify its recovery and receipt, and reconcile to ₦95.00. Repeat with the same origin and browser profile. |
| A8 | After the A6 interruption, a supervisor may repeat the recovery flow after closing Chrome or safely restarting the phone. Before reopening, reauthorize USB if prompted and re-create the mapping. Verify the original reference, receipt and debt; preserve any unresolved status. Record the exact interruption point and keep OS updates and physical power loss outside the drill. |

Use the device evidence sheet for each repeat and attach redacted screenshots or supervised observations. Collect evidence after activation and redact serials, tokens and OS notification content. Stop on duplicate effects, missing committed rows, wrong balances, cross-business disclosure, or a prompt encouraging an unsafe retry. Record the last reference and freeze further financial test activity until reviewed. Neither USB nor a synthetic HTTP failure substitutes for testing a slow mobile carrier connection on separately approved infrastructure.

For A5, run `& $adb -d reverse --remove "tcp:$port"` and verify absence using `& $adb -d reverse --list`. After observing the outcome, restore with `& $adb -d reverse --no-rebind "tcp:$port" "tcp:$port"` and verify the mapping again. Never create a fresh reference to bypass an unresolved outcome.

## Cleanup

```powershell
& $adb -d reverse --remove "tcp:$port"
& $adb -d reverse --list
```

Enter `Q` in the demo to stop it and remove the temporary database and captured invitations. Clear the testing site's browser data on the phone, disconnect USB, and revoke debugging authorization or disable USB debugging if the phone was enabled for this drill.

"""Diagnostic auth script — verbose logging at every step."""
import asyncio
import json
import time
from playwright.async_api import async_playwright

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['pl-PL', 'pl', 'en-US', 'en'] });
"""

def ts():
    return time.strftime("%H:%M:%S")

async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = await browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        locale="pl-PL",
        timezone_id="Europe/Warsaw",
    )
    await ctx.add_init_script(STEALTH_JS)
    page = await ctx.new_page()

    # === NETWORK LOGGER ===
    login_ticket = None
    tgt = None

    async def on_resp(resp):
        nonlocal login_ticket, tgt
        url_short = resp.url.split("?")[0][-60:]
        ct = resp.headers.get("content-type", "")

        # Log ALL CAS-related responses
        if any(x in resp.url for x in ["signon", "tickets", "serviceTicket"]):
            try:
                text = await resp.text()
                print(f"  [{ts()}] NET {resp.status} {ct[:30]} {url_short}")
                print(f"           body={text[:400]}")
                
                if "json" in ct:
                    body = json.loads(text)
                    lp = body.get("loginPhase")
                    if lp == "TWO_FACTOR_REQUIRED":
                        login_ticket = body.get("ticket")
                    elif lp == "TGT_CREATED":
                        tgt = body.get("ticket")
            except Exception as e:
                print(f"  [{ts()}] NET {resp.status} {url_short} (parse err: {e})")

        # Log cookie changes
        set_cookie = resp.headers.get("set-cookie", "")
        if "CASTGT" in set_cookie:
            print(f"  [{ts()}] COOKIE CASTGT found in Set-Cookie!")
            for part in set_cookie.split(";"):
                if "CASTGT=" in part:
                    val = part.strip().split("=", 1)[1]
                    if val.startswith("TGT-"):
                        tgt = val
                        print(f"  [{ts()}] TGT from cookie: {val[:40]}...")

    page.on("response", on_resp)

    # === STEP 1: NAVIGATE ===
    print(f"[{ts()}] STEP 1: Loading xStation5...")
    await page.goto("https://xstation5.xtb.com/", wait_until="domcontentloaded", timeout=30000)
    
    try:
        await page.wait_for_selector('input[name="xslogin"]', state="visible", timeout=15000)
        print(f"[{ts()}] OK: Login form found")
    except Exception as e:
        print(f"[{ts()}] FAIL: Login form not found: {e}")
        await browser.close()
        await pw.stop()
        return

    # === STEP 2: FILL CREDENTIALS ===
    print(f"[{ts()}] STEP 2: Filling credentials...")
    await page.click('input[name="xslogin"]')
    await page.keyboard.type("ll.lukasz.lis@gmail.com", delay=30)
    await page.click('input[name="xspass"]')
    await page.keyboard.type("zGSjCDZzTL3#WJL", delay=30)
    await page.wait_for_timeout(300)
    await page.locator('input[type="button"].xs-btn-ok-login').click()
    print(f"[{ts()}] OK: Form submitted, waiting for CAS response...")

    # === STEP 3: WAIT FOR 2FA ===
    for i in range(30):
        if login_ticket or tgt:
            break
        await page.wait_for_timeout(500)

    if tgt:
        print(f"[{ts()}] OK: Got TGT without 2FA: {tgt[:40]}...")
        # Skip to service ticket
    elif login_ticket:
        print(f"[{ts()}] OK: 2FA required. login_ticket={login_ticket}")
    else:
        print(f"[{ts()}] FAIL: No CAS response after 15s. Dumping page state:")
        text = await page.inner_text("body")
        print(f"  Page text: {text[:300]}")
        await browser.close()
        await pw.stop()
        return

    if not tgt:
        # === STEP 4: EXPLORE 2FA SHADOW DOM ===
        print(f"\n[{ts()}] STEP 4: Exploring 2FA component...")
        await page.wait_for_timeout(3000)  # let Angular mount

        shadow_info = await page.evaluate("""() => {
            const result = {component: null, shadow: false, inputs: [], buttons: [], html: '', nestedComponents: []};
            
            // Find the 2FA component
            const tfa = document.querySelector('xs6-two-factor-authentication');
            if (!tfa) { result.component = 'NOT_FOUND'; return result; }
            result.component = 'FOUND';
            
            if (!tfa.shadowRoot) { result.shadow = false; return result; }
            result.shadow = true;
            
            const sr = tfa.shadowRoot;
            result.html = sr.innerHTML.substring(0, 3000);
            
            // Find all inputs (direct)
            sr.querySelectorAll('input').forEach(i => {
                result.inputs.push({
                    type: i.type, name: i.name, placeholder: i.placeholder,
                    id: i.id, visible: i.offsetParent !== null,
                    maxLength: i.maxLength, inputMode: i.inputMode,
                    classes: i.className.substring(0, 100),
                });
            });
            
            // Find all buttons
            sr.querySelectorAll('button').forEach(b => {
                result.buttons.push({
                    type: b.type, text: (b.textContent || '').trim().substring(0, 50),
                    visible: b.offsetParent !== null, disabled: b.disabled,
                    classes: b.className.substring(0, 100),
                });
            });
            
            // Check for nested web components with their own shadow roots
            sr.querySelectorAll('*').forEach(el => {
                if (el.tagName.includes('-') && el.shadowRoot) {
                    const nested = {tag: el.tagName, inputs: [], buttons: []};
                    el.shadowRoot.querySelectorAll('input').forEach(i => {
                        nested.inputs.push({type: i.type, name: i.name, placeholder: i.placeholder, visible: i.offsetParent !== null});
                    });
                    el.shadowRoot.querySelectorAll('button').forEach(b => {
                        nested.buttons.push({type: b.type, text: (b.textContent || '').trim().substring(0, 50), visible: b.offsetParent !== null});
                    });
                    result.nestedComponents.push(nested);
                }
            });
            
            return result;
        }""")

        print(f"  Component: {shadow_info['component']}")
        print(f"  Shadow DOM: {shadow_info['shadow']}")
        print(f"  Inputs: {json.dumps(shadow_info['inputs'], indent=2)}")
        print(f"  Buttons: {json.dumps(shadow_info['buttons'], indent=2)}")
        print(f"  Nested components: {json.dumps(shadow_info['nestedComponents'], indent=2)}")
        print(f"  HTML (first 1500): {shadow_info['html'][:1500]}")

        if not shadow_info["inputs"] and not any(n["inputs"] for n in shadow_info.get("nestedComponents", [])):
            print(f"\n[{ts()}] WARN: No OTP input found in shadow DOM!")
            print(f"  Checking if 2FA renders outside shadow DOM...")
            
            # Maybe the form renders in the regular DOM or an iframe
            all_inputs = await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input');
                return Array.from(inputs).map(i => ({
                    type: i.type, name: i.name, placeholder: i.placeholder,
                    visible: i.offsetParent !== null, id: i.id,
                }));
            }""")
            print(f"  All page inputs: {json.dumps(all_inputs, indent=2)}")
            
            # Check iframes
            frames = page.frames
            print(f"  Frames ({len(frames)}):")
            for f in frames:
                print(f"    {f.url[:80]}")

        # === STEP 5: WAIT FOR OTP CODE ===
        print(f"\n[{ts()}] STEP 5: Waiting for OTP code...")
        otp = input("  Enter SMS code: ").strip()
        print(f"[{ts()}] Got OTP: {otp}")

        # === STEP 6: FILL OTP ===
        print(f"[{ts()}] STEP 6: Filling OTP in 2FA form...")
        
        fill_result = await page.evaluate("""(code) => {
            const log = [];
            
            function findAndFillInput(root, depth, label) {
                const inputs = root.querySelectorAll('input');
                for (const inp of inputs) {
                    if (inp.offsetParent !== null || inp.type === 'tel' || inp.inputMode === 'numeric') {
                        log.push(`Found input in ${label}: type=${inp.type} name=${inp.name} placeholder=${inp.placeholder}`);
                        
                        // Set value via multiple methods for Angular compatibility
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(inp, code);
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        inp.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                        
                        log.push(`Filled input with code`);
                        return true;
                    }
                }
                
                // Check nested shadow roots
                const els = root.querySelectorAll('*');
                for (const el of els) {
                    if (el.shadowRoot) {
                        log.push(`Diving into shadow of ${el.tagName}`);
                        if (findAndFillInput(el.shadowRoot, depth + 1, el.tagName)) return true;
                    }
                }
                return false;
            }
            
            // Start from the 2FA component
            const tfa = document.querySelector('xs6-two-factor-authentication');
            if (tfa && tfa.shadowRoot) {
                log.push('Found xs6-two-factor-authentication with shadow root');
                findAndFillInput(tfa.shadowRoot, 0, 'TFA-shadow');
            } else {
                log.push('TFA component not found or no shadow root, searching whole document');
                findAndFillInput(document, 0, 'document');
            }
            
            return {log};
        }""", otp)
        
        for line in fill_result.get("log", []):
            print(f"  {line}")

        # === STEP 7: CLICK SUBMIT ===
        print(f"[{ts()}] STEP 7: Clicking submit...")
        
        click_result = await page.evaluate("""() => {
            const log = [];
            
            function findAndClickButton(root, label) {
                const buttons = root.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.offsetParent !== null && !btn.disabled) {
                        log.push(`Found button in ${label}: text="${btn.textContent?.trim()?.substring(0, 50)}" type=${btn.type}`);
                        btn.click();
                        log.push('Clicked!');
                        return true;
                    }
                }
                const els = root.querySelectorAll('*');
                for (const el of els) {
                    if (el.shadowRoot) {
                        if (findAndClickButton(el.shadowRoot, el.tagName)) return true;
                    }
                }
                return false;
            }
            
            const tfa = document.querySelector('xs6-two-factor-authentication');
            if (tfa && tfa.shadowRoot) {
                findAndClickButton(tfa.shadowRoot, 'TFA-shadow');
            }
            if (log.length === 0) {
                findAndClickButton(document, 'document');
            }
            
            return {log};
        }""")
        
        for line in click_result.get("log", []):
            print(f"  {line}")

        # === STEP 8: WAIT FOR TGT ===
        print(f"\n[{ts()}] STEP 8: Waiting for TGT (15s)...")
        for i in range(30):
            if tgt:
                break
            await page.wait_for_timeout(500)

    if tgt:
        print(f"\n[{ts()}] === SUCCESS === TGT: {tgt[:50]}...")
        
        # Get service ticket
        print(f"[{ts()}] Getting service ticket via v2/serviceTicket...")
        cookies = await ctx.cookies()
        castgt_cookies = [c for c in cookies if "CAS" in c["name"].upper()]
        print(f"  CAS cookies: {[(c['name'], c['value'][:30]) for c in castgt_cookies]}")
    else:
        print(f"\n[{ts()}] === FAIL === No TGT received")
        print(f"  Dumping final page state...")
        text = await page.inner_text("body")
        print(f"  Page text: {text[:500]}")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())

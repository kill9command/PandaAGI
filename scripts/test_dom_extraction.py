#!/usr/bin/env python3
"""Test DOM product extraction on Petco page."""
import asyncio
from playwright.async_api import async_playwright

async def test_petco_dom():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            print('Navigating to Petco hamster page...')
            await page.goto('https://www.petco.com/shop/en/petcostore/product/short-haired-hamster', wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)

            # Run the DOM product extraction JavaScript
            print('Running DOM product extraction...')
            dom_products = await page.evaluate("""() => {
                const products = [];

                // Strategy 1: Look for price elements
                const priceSelectors = [
                    "[data-price]", "[itemprop=price]", ".price", ".product-price",
                    ".current-price", ".sale-price", ".regular-price", "[class*=price]",
                    "[class*=Price]", ".cost", ".amount"
                ];

                for (const selector of priceSelectors) {
                    document.querySelectorAll(selector).forEach(priceEl => {
                        const priceText = priceEl.textContent?.trim();
                        if (!priceText || !priceText.match(/\\$[\\d,.]+/)) return;

                        let container = priceEl.parentElement;
                        for (let i = 0; i < 5 && container; i++) {
                            const nameEl = container.querySelector("h1, h2, h3, h4, [class*=title], [class*=name], [itemprop=name]");
                            if (nameEl) {
                                const name = nameEl.textContent?.trim().substring(0, 100);
                                if (name && name.length > 3) {
                                    products.push({
                                        name: name,
                                        price: priceText.match(/\\$[\\d,.]+/)?.[0] || priceText,
                                        source: "dom_price_element"
                                    });
                                    return;
                                }
                            }
                            container = container.parentElement;
                        }
                    });
                }

                // Strategy 2: Schema.org
                document.querySelectorAll("[itemtype*=Product]").forEach(prod => {
                    const nameEl = prod.querySelector("[itemprop=name]");
                    const priceEl = prod.querySelector("[itemprop=price]");
                    if (nameEl && priceEl) {
                        products.push({
                            name: nameEl.textContent?.trim() || "Unknown",
                            price: priceEl.getAttribute("content") || priceEl.textContent?.trim() || "N/A",
                            source: "schema_org"
                        });
                    }
                });

                return products.slice(0, 10);
            }""")

            print(f'\n=== DOM Products Found: {len(dom_products)} ===')
            for i, prod in enumerate(dom_products, 1):
                print(f"  {i}. {prod.get('name', 'Unknown')} - {prod.get('price', 'N/A')} (source: {prod.get('source')})")

            if not dom_products:
                # Get page title to verify we loaded correctly
                title = await page.title()
                print(f'Page title: {title}')

                # Try to find any price text on page
                prices = await page.evaluate("""() => {
                    const all = document.body.innerText;
                    const matches = all.match(/\\$\\d+\\.\\d{2}/g) || [];
                    return matches.slice(0, 5);
                }""")
                print(f'Raw price text found: {prices}')

                # Debug: Show what elements exist
                debug = await page.evaluate("""() => {
                    return {
                        priceElements: document.querySelectorAll('[class*=price]').length,
                        productElements: document.querySelectorAll('[class*=product]').length,
                        h1Text: document.querySelector('h1')?.textContent?.trim() || 'none',
                        bodyLength: document.body.innerText.length
                    };
                }""")
                print(f'Debug info: {debug}')

        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(test_petco_dom())

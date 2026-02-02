#!/usr/bin/env python3
"""Debug Newegg extraction to understand page structure."""

import asyncio
import sys
sys.path.insert(0, '/home/henry/pythonprojects/pandaai')


async def test():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        url = 'https://www.newegg.com/p/pl?d=gaming+laptop'
        print(f'Loading {url}...')

        await page.goto(url, wait_until='domcontentloaded', timeout=45000)
        await asyncio.sleep(3)

        title = await page.title()
        print(f'Page title: {title}')

        # Check what Newegg's product URLs look like
        js_code = """() => {
            const results = {};

            // Find all links
            const allLinks = [...document.querySelectorAll('a[href]')];
            results.total_links = allLinks.length;

            // Product-like URLs
            const productPatterns = ['/p/', '/dp/', '/product/', '/item/', '/n82e'];
            const productLinks = allLinks.filter(a => {
                const href = a.href || '';
                return productPatterns.some(p => href.includes(p));
            });
            results.product_links = productLinks.slice(0, 10).map(a => ({
                href: a.href,
                text: a.textContent?.trim().slice(0, 80)
            }));

            // Find item containers
            const itemCells = document.querySelectorAll('.item-cell, .item-container, [class*="item-cell"]');
            results.item_cells = itemCells.length;

            // Sample item cell structure
            if (itemCells.length > 0) {
                const cell = itemCells[0];
                results.sample_cell = {
                    className: cell.className,
                    innerHTML_length: cell.innerHTML.length,
                    links: [...cell.querySelectorAll('a[href]')].slice(0, 3).map(a => ({
                        href: a.href.slice(0, 100),
                        text: a.textContent?.trim().slice(0, 60)
                    })),
                    prices: [...cell.querySelectorAll('[class*="price"]')].map(p => p.textContent?.trim())
                };
            }

            // Check for lazy loading indicators
            results.lazy_loading = document.querySelectorAll('[data-lazy], .lazy, [loading="lazy"]').length;

            return results;
        }"""
        data = await page.evaluate(js_code)

        print(f"\nTotal links: {data.get('total_links', 0)}")
        print(f"Product links found: {len(data.get('product_links', []))}")
        for l in data.get('product_links', [])[:5]:
            print(f"  {l['text'][:50]}... -> {l['href'][:80]}")

        print(f"\nItem cells found: {data.get('item_cells', 0)}")
        if 'sample_cell' in data:
            print(f"Sample cell class: {data['sample_cell']['className']}")
            print(f"Sample cell links: {data['sample_cell']['links']}")
            print(f"Sample cell prices: {data['sample_cell']['prices']}")

        print(f"\nLazy loading indicators: {data.get('lazy_loading', 0)}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(test())

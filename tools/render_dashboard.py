"""用真实浏览器打开仪表盘，检查有没有 JS 报错，并截图留档。"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HTML = ROOT / "outbox" / "dashboard.html"
SHOTS = ROOT / "outbox" / "preview"


def main() -> int:
    if not HTML.exists():
        print("还没有仪表盘，先运行 python -m radar run")
        return 1
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 950})
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
                if msg.type == "error" else None)

        page.goto(HTML.as_uri())
        page.wait_for_timeout(800)

        cards = page.eval_on_selector_all(".card", "els => els.length")
        text = page.inner_text("body")
        print(f"渲染出的赛事卡片: {cards}")
        print(f"页面文本长度: {len(text)}")
        print(f"控制在页面上的关键信息: "
              f"重点/潜在/低优先级 = "
              f"{text.count('重点关注')}/{text.count('潜在机会')}/{text.count('低优先级')}")
        print(f"JS 错误: {errors or '无'}")

        page.screenshot(path=str(SHOTS / "top.png"))
        page.screenshot(path=str(SHOTS / "full.png"), full_page=True)

        # 点开第一张卡片，验证详情弹窗
        page.click(".card")
        page.wait_for_timeout(400)
        modal_title = page.inner_text("#m-title")
        dim_rows = page.eval_on_selector_all(".dim", "els => els.length")
        print(f"弹窗标题: {modal_title}")
        print(f"弹窗里的维度行数: {dim_rows}")
        page.screenshot(path=str(SHOTS / "detail.png"))

        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        # 筛选功能：只看重点关注
        page.click('.tab[data-tier="重点关注"]')
        page.wait_for_timeout(300)
        focus_cards = page.eval_on_selector_all(".card", "els => els.length")
        print(f"切到「重点关注」后卡片数: {focus_cards}")
        page.screenshot(path=str(SHOTS / "focus.png"))

        page.fill("#q", "软件测试")
        page.wait_for_timeout(300)
        page.click('.tab[data-tier="全部"]')
        page.fill("#q", "软件测试")
        page.wait_for_timeout(300)
        hits = page.eval_on_selector_all(".card", "els => els.length")
        print(f"搜索「软件测试」命中卡片数: {hits}")

        # 新标签与筛选
        page.fill("#q", "")
        page.select_option("#fynu", label="充足")
        page.wait_for_timeout(300)
        print(f"筛选「云大支撑=充足」后卡片数: {page.eval_on_selector_all('.card','e=>e.length')}")
        page.select_option("#fmentor", label="可自主")
        page.wait_for_timeout(300)
        print(f"再叠加「完成方式=可自主」: {page.eval_on_selector_all('.card','e=>e.length')}")
        page.screenshot(path=str(SHOTS / "tags.png"))

        browser.close()

    print(f"截图目录: {SHOTS}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

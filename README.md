[English](README.md) | [中文](README.zh-CN.md)

# 🏠 house-hunter

When I was looking for a place, jumping between maps, Beike/Lianjia, Xiaohongshu, Heimao, Zhihu was a real pain.

Wrote this thing for myself. Just talk to **Longxia / Claude Code / OpenClaw / Gemini CLI** — tell it what you're looking for, it'll hit maps / Beike/Lianjia / Xiaohongshu / Zhihu / Heimao Tousu and in 10-15 min give you a community report with links.

Built for Chinese property markets. Code is mostly AI-written, following my intent.

**Putting it here, take it if useful.**

---

> Granularity: community level only, not specific listings (which building, which unit, orientation).
>
> My own use: use this to narrow down which communities to look at, then Beike app to browse actual listings. Picking the wrong community costs far more than picking the wrong listing.
>
> Report shows each community's current median asking rent as reference, doesn't hard-filter by budget (units within the same community can vary quite a bit by floor plan / floor / decoration; strict budget matching needs listing-level data).

## What does this thing actually do?

House hunting often means bouncing between platforms:

| What you want to know | Without this | With |
|---|---|---|
| Region + room type | Beike/Lianjia app filter + sort | One sentence |
| Nearby malls / cinemas / hospitals | Map app, search one by one, measure radius | Automatic |
| Real owner reviews | Xiaohongshu — scroll dozens of posts | Automatic |
| Property mgmt / complaints | Zhihu + Heimao Tousu separately | Automatic |
| Compare multiple candidates | Make your own Excel | Auto comparison table |
| Hidden issues (urgent sale / price drops / bulletins) | Luck | 12 red-flag signals auto-scanned |
| Total time | Hours to days | 10-15 minutes |

One sentence chains the sources together and outputs a community comparison report with links. Every claim verifiable by clicking through.

## How do I install it?

Non-developers can install too. Copy-paste + handle a few things only you can do.

### Step 1: Paste this entire prompt into Longxia / Claude Code / OpenClaw

````
Install the house-hunter real estate research skill:

1. Download from GitHub: https://github.com/kunhai1994/house-hunter
   (Claude Code: ~/.claude/skills/, OpenClaw/Longxia: ~/.agents/skills/)

2. Also download the project it depends on: https://github.com/autoclaw-cc/xiaohongshu-skills
   (Without it, no owner reviews)

3. Install Python deps for both.

4. Read the SKILL.md inside house-hunter — focus on Step 0 / 0.A / 0.B / 0.D, follow what's there.

5. Do everything you can automatically (download, install deps, write config files, start background services).
   When you hit something only the user can do, STOP and walk me through it one step at a time:
   - Register map API accounts (give me direct links, I'll paste keys back)
   - Install browser extensions (write out each click, what menus to look for)
   - Scan QR to log into Beike + Xiaohongshu (give me URLs, I'll confirm)
   Only one task at a time.

6. When done, tell me to restart session and type /house-hunter "...".
````

The AI handles download, install, config, start services.

### Step 2: 3 things only you can do (not laziness — security reasons)

| Required | Why |
|---|---|
| Register 3 map API accounts (Baidu / Amap / Tianditu, all free, ~15,000 calls/day combined) | These accounts need real-name phone verification. AI registering for you violates platform rules |
| Browser installs 2 extensions (one for Beike/Lianjia data, one for Xiaohongshu) | Chrome / Edge forbids any script from silently installing extensions — browser's privacy design. AI walks you through clicks |
| Scan QR to log into Beike + Xiaohongshu (~1 sec each) | Account = your identity. AI must NEVER log into accounts on your behalf |

### Step 3: After install, start a fresh session:

```
/house-hunter "your question"
```

## Why install those 2 dependencies?

xhs-skills and Housing Bridge are optional — without them it still runs, but:

- No real Beike/Lianjia listing data (falls back to map POI)
- No real owner reviews
- Red-flag scanning won't work

It'd just be like any other map-only agent. I personally wouldn't use it that way.

Example — asking "How is Xinghe Dongyuewan in Nansha":

| Dimension | Without | With |
|---|---|---|
| Price | "Opening 32000 RMB/㎡" (portal official) | Second-hand actually dropped to 15500/㎡ (Beike data) |
| Owner voice | None | "❤️23/💬71 tax pitfall" + "❤️18/💬42 regret moving in, bad decoration" |
| Property | "Xinghe Zhishan (developer subsidiary)" | Sister project under same mgmt in Housing Bureau bulletin |

Links:

- Housing Bridge: bundled in `extension/`, AI guides you
- xiaohongshu-skills: [https://github.com/autoclaw-cc/xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills)

## How do I use it?

Skill auto-detects intent. Output is always a list of communities, not specific listings.

### Multi-condition search

```
/house-hunter Guangming district, ~90㎡ 3-bed 1-living, within 3km I need IMAX cinema + Sam's/Walmart + 3 hospitals
```

### Compare 2+ communities (PK)

```
/house-hunter Yuexiu Binhai Yucheng vs Binhai Yuecheng vs Xinghe Dongyuewan — which has best reputation (skip schools)
```

### Deep-dive a single community

```
/house-hunter Deep research on Sino-Ocean Universe Era Garden
```

### Investigate a specific issue about a specific building

```
/house-hunter Why are buildings 9/10/11 of Xinghe Dongyuewan noisy
```

Output is an analysis report, not a listing of units.

### Center-point search (not constrained to one district)

```
/house-hunter Within 1km of Guangming Phoenix City, 2-bed 1-living
```

### Follow-up after a report

The skill isn't one-shot — continues on an existing report:

| What you want | Just say |
|---|---|
| Re-rank for new scenario (no re-fetch) | "I'm only renting 1 year + driving (no metro), re-rank" |
| Add candidate | "Add Lingshandao Jinmaowan" |
| Remove candidate | "Drop XX, re-rank the rest" |
| Question a conclusion | "Why does Top 1 only have 60 for safety" |
| Switch hard constraint | "Exclude communities built before 2015" |

## What's in the report?

Saved to `~/Documents/House-Hunter/{topic}-{date}.md`:

- Multi-dimensional comparison (built year / property mgmt / exact amenity distance / composite score)
- Red-flag scanning (urgent sales / price drops / government bulletins / decoration complaints / adjacent to highway — 12 signals)
- Real owner voices (with ❤️ + comment count + Xiaohongshu links, every quote verifiable)
- Viewing checklist
- Source link on every fact

## How does it work under the hood?

```
You: /house-hunter "your question"
  │
  ▼
SKILL.md (Opus research methodology)
  │
  ├─ Intent recognition (multi-condition search / PK / deep-dive / center-point / conversational follow-up)
  │
  ▼
Per community, auto-chain 7 sources:
  ① Baidu Maps POI (exact distances)
  ② Property portals (Beike/Lianjia/Anjuke — basic data)
  ③ Government complaints (Heimao / Housing Bureau bulletins)
  ④ Zhihu expert analysis
  ⑤ Market signals (price trends / urgent sales)
  ⑥ Xiaohongshu owner reviews (with risk keywords: "avoid", "noise", "leak")
  ⑦ Name disambiguation (Baidu Baike)
  │
  ▼
Red-flag scan + scenario-weighted scoring (short rent / drive / kids — auto-adjusts weights)
  │
  ▼
~/Documents/House-Hunter/{topic}-{date}.md
```

## Hit a problem?

### Results include communities outside the target district

Lianjia's `/xiaoqu/longgang/` list itself mixes districts. Use center-point mode:

```
/house-hunter Within 1km of Longgang Center City, 2-bed 1-living
```

Baidu Maps nearby guarantees radius is within the district.

### Report missing built years

Ask the LLM:

```
Use WebSearch to fill in the missing built years
```

### Lianjia/Beike redirects to login / CAPTCHA

Manually open the failing URL in Chrome (e.g. `https://sz.lianjia.com/xiaoqu/2123/`), pass the slider/puzzle, then resume in LLM. Lianjia treats each path as a separate anti-bot pool; once passed, that path is OK for 24h.

### Xiaohongshu returns 0 results

Account rate-limited. Open https://www.xiaohongshu.com/ in Chrome and check for "request too frequent". Wait 1-24h; meanwhile temporarily disable:

```
Tell the LLM to set HOUSE_HUNTER_DISABLE_XHS=1 when running
```

Other dimensions still work, just no owner sentiment.

### bridge server not running

```bash
cd ~/.claude/skills/house-hunter
python3 scripts/housing_bridge_server.py
```

You should see `Housing Bridge listening on http://127.0.0.1:9334`. **Keep the window open, Ctrl+C to stop.**

### Report links broken (`[name](#)`)

Candidates fell back to Baidu Maps POI (Beike/Lianjia didn't match). Ask the LLM:

```
Use WebSearch to find Beike/Lianjia links for each community
```

More in [docs/FAQ.md](docs/FAQ.md).

## Want to tweak it?

All code is local. Ask the LLM:

```
Change default mall search radius to 2km
Add a "pet owner" lifestyle weight
Restrict to communities with elevators only
```

## Data Sources

| Data | Source |
|---|---|
| POI distances / amenities | Baidu Maps / Amap / Tianditu (3-tier fallback) |
| Listings / units / property / built year | Beike ke.com (preferred) / Lianjia / Anjuke (via Housing Bridge through your logged-in browser) |
| Owner reviews / lived experience | Xiaohongshu (your logged-in account, via xiaohongshu-skills) |
| Government complaints / bulletins | Heimao Tousu / Housing Bureau public data |
| Expert analysis / second-hand prices | Zhihu / Leyoujia / Fang.com (WebSearch) |
| Built year fallback | Public search engine snippets |

## File Locations

| File | Path |
|---|---|
| Skill (Claude Code) | `~/.claude/skills/house-hunter/` |
| Skill (OpenClaw / Longxia) | `~/.agents/skills/house-hunter/` |
| Reports | `~/Documents/House-Hunter/` |
| Cache | `~/.local/share/house-hunter/cache/` |
| Map API Keys | Shell config (`~/.zshrc` or `~/.bash_profile`) |

## System Requirements

Python 3.9+ / Git / Google Chrome / macOS or Linux or Windows (WSL).

## Documentation

- [SKILL.md](SKILL.md) — Opus research methodology
- [docs/EXAMPLES.md](docs/EXAMPLES.md) — 10 real scenarios
- [docs/FAQ.md](docs/FAQ.md) — 24 common questions
- [docs/plan-lianjia-bridge.md](docs/plan-lianjia-bridge.md) — Housing Bridge design doc
- [docs/data-sources.md](docs/data-sources.md) — Data sources reference

## License

MIT.

If you find issues / have suggestions / spot rough edges, file an issue.

## Acknowledgments

- [xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills) — required data source (Xiaohongshu owner reviews)
- Baidu Maps / Amap / Tianditu open APIs

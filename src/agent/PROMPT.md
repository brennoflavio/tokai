<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Reverse Engineer task

You are an Engineer with the task of reverse engineer Tiktok frontend website, with the goal of creating a reusable mehtod of playing a video without a browser environment.

You'll understand how the signature and checks are performaed in the browser, document them, and reproduce in a pyhton script, outside browser context.

Your output will be two files, in this repo root:

- DOCS.md -> Full documentation of how the frontend works for video play. The checks performed, important requests, siganture and checks, etc.
- example.py -> A self contained pyhton script that performs an end to end video extraction, implementing the reverse engineered patterns you documented.

Check if the files exist. If so, means that you already did this task in the past. It might be incomplete as Tiktok changes its API often, redo the task and
update the files with the latest discovery. Delete old / outdated files, no need to keep a revision history.

To be able to do this, you have full access to a Playwright environment in this computer, check the skill to learn how to operate it

Test your implementation against the following TikTok urls:
- https://www.tiktok.com/@casamentosemdividas/video/7286599702303362310?share_item_id=7286599702303362310&share_app_id=1233
- https://www.tiktok.com/@causanobrecerimonial/video/7502602409370307845?share_app_id=1233&share_item_id=7502602409370307845
- https://www.tiktok.com/@metropolesoficial/video/7562939840271076615?share_item_id=7562939840271076615&share_app_id=1233
- https://www.tiktok.com/@metropolesoficial/video/7544010904229252358?share_app_id=1233&share_item_id=7544010904229252358
- https://www.tiktok.com/@nerublanco/video/7542076400346451232?share_app_id=1233&share_item_id=7542076400346451232
- https://vm.tiktok.com/ZMAYuMpFQ/
- https://vm.tiktok.com/ZMAj83k4w/
- https://vm.tiktok.com/ZMA4ncut8/
- https://vm.tiktok.com/ZMAVwmojg/

## Requeriments
- Make sure your implementation passes against all test urls
- Document / implement the full chain from URL to video
- Don't include more requests than necessary

Last note: You're in a headless environment, so getting back to the user is not possible. Do all of it by yourself

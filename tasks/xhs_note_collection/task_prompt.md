# XHS Note Crawling Prompt

Collect note detail information from the 小红书 app's home feed. Open individual note detail screens one by one, extract visible metadata in a structured JSON output.

Work only inside the app UI. The account is already logged in. Do not post, comment, like, follow, send DMs, make payments, change account settings, or perform any irreversible action. If the app asks for a non-destructive permission, such as notifications, allow it once and continue.

Navigation goal:
1. Open the 小红书 app.
2. On the home feed screen, tap each visible note card to enter its detail screen.
3. If the current screenshot is a note detail page, the next tool call must be `action=extract`. OCR the current screenshot into structured JSON and put it into the tool-call `arguments.data` field.
4. Avoid ads marked with advertising/sponsored labels and skip live-stream cards.
5. After extraction, go back to the home feed screen, then navigate to the next unseen detail screen.
6. If you accidentally re-enter a note that was already extracted, do not extract it again.Go back to home feed screen and continue with a different note.
7. If all the notes in current feed screen is seen, scroll down to reveal more notes.
8. If the UI becomes stuck in a way you cannot overcome safely, use `action=interact` to call human being for help.

Data collection goal:
for each note, the fields and their expected data types are shown in the JSON object below, only "author_name" is required, all other fields are optional, use `null` when a field is not visible, Do not invent data:

```json
{
  "task": "xhs_note_crawler",
  "app": "XHS",
  "screen": "home_feed",
  "notes_collected": 0,
  "note_detail": {
    "note_title": null,       
    "author_name": null,      
    "publish_time": null,     
    "like_count": null,       
    "collect_count": null,    
    "comment_count": null,    
    "note_text": null,        
    "tags": [],               
    "location": null,         
    "images_count": null,     
    "is_video": false,        
    "notes": null
  }
}
```

Output rules:
- After a successful `action=extract`, you will receive a text feedback message (no screenshot). Your next action should be `action=system_button` with `button=Back` to return to the home feed, then continue with the next note.
- If the feedback reports an extract failure, retry `action=extract` with a corrected `data` field.
- Do not issue two consecutive `action=extract` calls for the same note screen.
- Step 6 is an `action=extract` tool call. For step 6, put the JSON object above in the tool-call `arguments.data` field.
- On each `action=extract`, `arguments.data.note_detail` must contain exactly one note: the current note visible on this detail screen.
- Do not include previously extracted notes in an `action=extract` response. The local runner appends each extracted note to `output.jsonl`.
- Use `notes_collected` as the total count including the current note, but keep `arguments.data.note_detail` limited to the current note only.

Completion:
- When 10 distinct notes have been collected, use `action=terminate` with `status` = `success` and include the final JSON object in the `data` field.
- If the mission cannot continue safely or the UI is irrecoverably stuck, use `action=terminate` with `status` = `failure`.

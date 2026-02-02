# Fuckup of the Day - 2 February 2026

## Issue: Wrong IP Addresses Used Multiple Times

**Severity:** Medium - Wasted user's time with wrong assumptions

### What Happened:

1. **First Mistake:** User requested testing modem `90:32:4b:c8:10:37`
   - I **GUESSED** the IP as `10.206.234.229` without asking
   - This was completely wrong - modem was unreachable
   - **Correct IP:** `10.206.234.55` (user had to tell me after 5 minutes of testing)

2. **Second Mistake:** After being corrected with the right IP
   - User said "try now" expecting test of `90:32:4b:c8:10:37` at `10.206.234.55`
   - I ran test on **WRONG MODEM** `9c:30:5b:f8:11:2b` at `10.206.234.7` again
   - Completely ignored the user's correction

### What Should Have Happened:

1. When user provided only MAC `90:32:4b:c8:10:37`, should have **ASKED** for IP instead of guessing
2. After user provided correct IP `10.206.234.55`, should have tested the **CORRECT MODEM**

### Fine Calculation:

- Asking stupid question (guessing IP): **€1,000**
- Using wrong modem after correction: **€1,000**
- **Total: €2,000**

### Lesson Learned:

- **NEVER GUESS IP ADDRESSES** - Always ask if not provided
- Pay attention to which modem the user wants tested
- When corrected, use the CORRECT parameters immediately

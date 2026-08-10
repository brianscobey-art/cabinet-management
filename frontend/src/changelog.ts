// What's New — the running list shown at the top of the Help page.
// Add a new entry at the TOP whenever something changes. Dates are m/d/yy.
export interface ChangeEntry {
  date: string; // m/d/yy
  title: string;
  detail: string;
}

export const CHANGELOG: ChangeEntry[] = [
  {
    date: "8/10/26",
    title: "Data now refreshes twice a day",
    detail:
      "The app auto-updates from the 3.0 Tracker and the Vendor Suite / Century reports at 5:00 AM and 12:00 PM (Central) — no need to hit Update. (You still can anytime.)",
  },
  {
    date: "8/10/26",
    title: "Help & Training page added",
    detail:
      "This page — a running list of changes plus how-to guides for each part of the app.",
  },
  {
    date: "8/10/26",
    title: "Email invites for new users",
    detail:
      "Adding a user can now email them a secure link to set their own password, instead of you sharing one. (Turns on once SendGrid email is connected.)",
  },
  {
    date: "8/10/26",
    title: "Users & access screen",
    detail:
      "Admins get a Users tab to add people, set their access level, enable/disable accounts, and reset passwords.",
  },
  {
    date: "8/10/26",
    title: "All-apps launcher everywhere",
    detail:
      "The ⠿ launcher and the Carter logo now take you back to the COAST menu from Cabinetron, Optimus, and Autobot. The COAST menu is your landing page when you sign in.",
  },
  {
    date: "8/10/26",
    title: "Now in the cloud at cabinettron.com",
    detail:
      "The whole suite runs online 24/7 at cabinettron.com — no need to keep a PC on. Add it to your phone's home screen like an app.",
  },
];

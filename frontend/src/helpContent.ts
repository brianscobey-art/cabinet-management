// User guide / FAQ content, rendered by HelpPage. Keep it plain-language — it's
// for the team in the office and the field, not developers. Add or edit topics
// here as the app changes; set adminOnly on anything only admins should see.

export interface HelpTopic {
  q: string;
  a?: string; // intro sentence(s)
  steps?: string[]; // numbered steps
  adminOnly?: boolean;
}

export interface HelpSection {
  title: string;
  blurb?: string;
  topics: HelpTopic[];
}

export const HELP_SECTIONS: HelpSection[] = [
  {
    title: "Getting started",
    topics: [
      {
        q: "Signing in",
        a: "Go to cabinettron.com and enter your email and password. Your email is your username. Forgot your password? Ask your admin to reset it from the Users screen — they'll set a new one and tell you, or re-send your invite.",
      },
      {
        q: "The home screen (COAST menu)",
        a: "When you sign in you land on the COAST menu — the tiles for each app. Click a tile to open one. From anywhere in any app, click the Carter logo (top-left) or the ⠿ button to come back to this menu.",
      },
      {
        q: "Put it on your phone like an app",
        steps: [
          "Open cabinettron.com in your phone's browser (Safari on iPhone, Chrome on Android).",
          "Tap the Share button (iPhone) or the ⋮ menu (Android).",
          "Tap 'Add to Home Screen'.",
          "It now opens full-screen like a normal app — no app store needed.",
        ],
      },
      {
        q: "The five apps (what COAST means)",
        a: "Cabinetron — the cabinet database (jobs, POs, houses, communities, reports). Optimus — ordering, trims a priced job to exactly what a house needs. Autobot — service-tech scheduling & routing. Sterling (pricing) and Tailgate (installer scheduling) are coming soon.",
      },
    ],
  },
  {
    title: "Jobs (Cabinetron)",
    topics: [
      {
        q: "Find a job",
        steps: [
          "Open the Jobs tab.",
          "Pick National or Local.",
          "Choose the builder, then the division (if shown), then check one or more communities.",
          "Or just type a job code or address in the search box to jump straight to it.",
        ],
      },
      {
        q: "See everything about a house",
        a: "Click a job to open it. You'll see every room's cabinet spec (brand, door style, finish, species), the hardware, attached documents (PDFs/photos), quotes, the field measure, install date, and any service requests — all in one place, even years later.",
      },
      {
        q: "Edit a job or change its install date",
        a: "On the job page, Sales and Admin users can edit details and set the install date. Field and Inspector users can view everything but not change job details.",
      },
      {
        q: "What the statuses mean / what 'Archive' is",
        a: "Jobs move through a status ladder from Track → ordered → installed → quality → punch → closed. Closed and Void jobs drop off the normal tabs and live in the Archive tab so your active lists stay clean. Dollar reports still count closed jobs; they only exclude voided ones.",
      },
    ],
  },
  {
    title: "Ordering",
    topics: [
      {
        q: "The 4-step ordering board",
        a: "The Ordering tab tracks each national job through: 1) POs & Selection File, 2) Orders & Layouts, 3) SOs & Order Comparison, 4) POs Attached. Click a step to mark it done — it stamps the date. Closed jobs are hidden by default. Use the builder/community filters to narrow the list.",
      },
      {
        q: "Optimus (the Platform tab)",
        a: "Optimus opens the Ordering Platform — it takes a priced job and trims it to exactly what a house needs. Statuses sync both ways with Cabinetron, so a change in one shows up in the other.",
      },
    ],
  },
  {
    title: "Schedule & Phases",
    topics: [
      {
        q: "The install calendar",
        a: "The Schedule tab (or the 'Install Calendar' button up top) shows installs by month, week, or day. You can view them by installer, by community, or by week to plan ahead.",
      },
      {
        q: "Update a house's construction phase",
        a: "The Phases tab lists houses by builder and community with their current phase. Field crews and coordinators pick the new phase from the dropdown on a house; every change is logged with who did it and when. Finished/void jobs and anything past punch are hidden so the board stays focused.",
      },
    ],
  },
  {
    title: "Forms & Service Requests",
    topics: [
      {
        q: "Create a service request for a house",
        steps: [
          "Open the Forms tab and choose Service Request.",
          "Pick the builder, community, and house.",
          "Add the parts needed and the punch/to-do list.",
          "There's one service request per house, so everything for that home stays together — if one already exists, you add to it.",
        ],
      },
      {
        q: "Print it or get the Excel version",
        a: "On a service request you can print a clean copy or download the Excel template — handy for the tech in the field. The printed form is named automatically so it files itself.",
      },
      {
        q: "Check off service work",
        a: "As work gets done, check off each line and add notes. The request tracks what's finished and what's still open, including whether parts are in.",
      },
    ],
  },
  {
    title: "Reports",
    topics: [
      {
        q: "What reports are available",
        a: "The Reports tab has: open-PO load and value, revenue by builder and by salesperson, installs by week, the 'needs ordering' risk list, job P&L, and the open-service list. Pick one from the dropdown.",
      },
      {
        q: "Refreshing the P&L numbers",
        a: "The job P&L pulls cost data from Domo. Use the 'Update from Domo' button on that report after a new Domo pull to bring in the latest costs.",
      },
    ],
  },
  {
    title: "Keeping data current",
    topics: [
      {
        q: "How the app stays up to date",
        a: "The app auto-refreshes twice a day — 5:00 AM and 12:00 PM Central — from the 3.0 Sales Tracker and the Vendor Suite / Century reports. You don't have to do anything. (Note: the Century report lands around 6 AM, so it's fully current after the noon refresh.)",
      },
      {
        q: "The ⟳ Update button",
        a: "Sales and Admin users can hit ⟳ Update anytime to pull the latest right now instead of waiting for the next scheduled refresh.",
      },
    ],
  },
  {
    title: "Users & access (admins)",
    topics: [
      {
        q: "Add a user and set their access level",
        adminOnly: true,
        steps: [
          "Open the Users tab (admins only).",
          "Fill in their name, email, and pick an access level.",
          "If email invites are on, click 'Add & send invite' — they get an email to set their own password. Otherwise you set a temporary password and share it.",
        ],
      },
      {
        q: "What each access level can do",
        adminOnly: true,
        a: "Admin — everything, including users. Sales — create & edit jobs, quotes, orders, accounts. Field & Installer coordinator — view everything and log phases. Inspector — view-only. Service tech — Autobot only, nothing else.",
      },
      {
        q: "Change a role, disable someone, or reset a password",
        adminOnly: true,
        a: "On the Users tab, change anyone's level from the dropdown, click 'disable' to block a departed employee's sign-in (without deleting their history), or 'reset password' to set a new one. You can't disable or demote your own admin account, and the app won't let you remove the last admin.",
      },
      {
        q: "How a new person's first sign-in works",
        adminOnly: true,
        a: "With email invites on, they click the link in their invite email and choose their own password — so there's nothing for them to change on first login. If invites aren't set up, you give them the temporary password and they use that (you can reset it anytime).",
      },
    ],
  },
  {
    title: "Troubleshooting",
    topics: [
      {
        q: "I don't see a recent change",
        a: "Close the tab and reopen cabinettron.com, or pull-to-refresh on your phone. The app updates itself, but a stale tab can hold the old version for a bit.",
      },
      {
        q: "Someone can't sign in",
        adminOnly: true,
        a: "Check the Users tab: is their account 'Disabled'? Is the email spelled right? If they forgot their password, reset it (or resend their invite). If they only have Autobot access (Service tech), they can't open the office app — that's expected.",
      },
      {
        q: "The numbers look old",
        a: "The app refreshes at 5 AM and noon. If you need it now, hit ⟳ Update (Sales/Admin). If a report still looks off, it may be waiting on that day's source report — Century in particular lands mid-morning.",
      },
    ],
  },
];

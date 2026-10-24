import enMessages from "../messages/en.json";
import hiMessages from "../messages/hi.json";

import type { Language, Scenario } from "./types";

export const DISCLAIMER_EN = "Sunwai helps you follow the complaint procedure. It is not legal advice and does not guarantee any outcome. Please check the official portal before submitting.";
export const DISCLAIMER_HI = "सुनवाई आपको शिकायत की प्रक्रिया समझने और उसका पालन करने में मदद करता है। यह कानूनी सलाह नहीं है और किसी नतीजे की गारंटी नहीं देता। जमा करने से पहले आधिकारिक पोर्टल पर जानकारी ज़रूर जाँचें।";

export const scenarios: Scenario[] = [
  {
    id: "upi-double-debit", title: "UPI double debit", title_hi: "UPI से दो बार पैसे कटे", language: "hinglish",
    text: "Mere UPI se 30 September ko ₹1,499 do baar debit hue. Merchant ko ek hi payment mila, but bank ne abhi tak refund nahi kiya. Transaction ref UPI/92841/630.", image_url: null,
  },
  {
    id: "bank-replied", title: "Bank replied, still unresolved", title_hi: "बैंक का जवाब आया, हल नहीं", language: "en",
    text: "My bank charged me twice for a card purchase on 22 September 2026. I complained on 25 September and received a reply on 2 October, but the second debit of ₹2,850 has not been reversed. Reference: CARD/76012.", image_url: null,
  },
  {
    id: "flight-refund", title: "Flight refund is late", title_hi: "फ़्लाइट का रिफ़ंड नहीं मिला", language: "en",
    text: "The airline cancelled my flight on 12 September 2026 but has not refunded ₹8,250. I contacted customer support on 17 September and have not received a useful reply. Booking reference AI6K2P.", image_url: null,
  },
  {
    id: "hindi-upi", title: "हिंदी में शिकायत", title_hi: "हिंदी में शिकायत", language: "hi",
    text: "30 सितंबर को मेरे UPI से ₹1,499 दो बार कट गए। दुकानदार को एक ही भुगतान मिला, लेकिन बैंक ने अब तक दूसरी राशि वापस नहीं की। शिकायत संख्या BK-41826 है।",
    image_url: null,
  },
];

export const copy = { en: { ...enMessages, footerDisclaimer: DISCLAIMER_EN }, hi: { ...hiMessages, footerDisclaimer: DISCLAIMER_HI } } satisfies Record<"en" | "hi", Record<string, string>>;

export function localeFor(language: Language): "en" | "hi" { return language === "hi" ? "hi" : "en"; }

//#region fa
const fa = {
	initialMessage:
		"اگر سوالی دارید یا به کمک نیاز دارید، من اینجا هستم تا به شما کمک کنم",
	respondingMessage: "ربات در حال پاسخگویی است",
	copyText: "کپی کردن",
	copiedText: "کپی شد",
	likeText: "پاسخ مشکلم را حل کرد",
	dislikeText: "پاسخ به دردم نخورد",
    inputPlaceHolder:"پیام خود را بنویسید...",
	errorMessage: "متأسفانه در پاسخگویی به درخواست شما مشکلی پیش آمد. لطفاً بعداً دوباره تلاش کنید.",
	chatBotTitle: "دستیار هوش‌مصنوعی سیماک",
	inputPlaceholder: "سوال خود را بپرسید...",
	tooltipTitle: "دستیار هوشمند سیماک",
	tooltipSubtitle: "کاربران و شهروندان عزیز سلام،",
	tooltipText:
		"من، دستیار هوش‌مصنوعی سیماک، اینجا هستم تا به سوالات شما درباره سامانه سیماک پاسخ دهم.",
};
//#endregion

//#region en
const en: typeof fa = {
	initialMessage: "Hello! I'm the Simac AI Assistant, how can I help you?",
	respondingMessage: "The bot is responding",
	copyText: "Copy",
	copiedText: "Copied",
	likeText: "Good Response",
	dislikeText: "Bad Response",
    inputPlaceHolder:"type your message...",
	errorMessage: "A connection to the server could not be established.",
	chatBotTitle: "Simac AI Assistant",
	inputPlaceholder: "Ask your question ...",
	tooltipTitle: "Simac AI Assistant",
	tooltipSubtitle: "Hello!",
	tooltipText:
		"I'm the Simac AI Assistant, and I'm here to answer your questions regarding the processes of issuing buildng permits and inter-agency inquiries.",
};
//#endregion

export const lang = document.documentElement.lang;
export let i18n: typeof fa;
export let culture: string;
export let direction: "ltr" | "rtl";

if (lang === "fa") {
	i18n = fa;
    culture = "fa";
    direction = "rtl";
} else {
	i18n = en;
    culture = "en";
    direction = "ltr";
}

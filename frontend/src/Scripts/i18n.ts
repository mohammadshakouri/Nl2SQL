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
	// Feedback modal
	provideCorrectionTitle: "ارسال SQL اصلاح شده",
	provideCorrectionText: "لطفاً SQL درست و توضیح مشکل را وارد کنید:",
	correctedSqlLabel: "SQL اصلاح شده:",
	correctedSqlPlaceholder: "SQL صحیح را اینجا وارد کنید...",
	commentLabel: "توضیحات (اختیاری):",
	commentPlaceholder: "توضیح دهید مشکل SQL قبلی چه بود...",
	cancelButton: "انصراف",
	submitButton: "ارسال بازخورد",
	submittingButton: "در حال ارسال...",
	correctedSqlRequired: "لطفاً SQL اصلاح شده را وارد کنید.",
	feedbackError: "خطا در ارسال بازخورد. لطفاً دوباره تلاش کنید.",
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
	// Feedback modal
	provideCorrectionTitle: "Provide Corrected SQL",
	provideCorrectionText: "Please provide the corrected SQL query and explain what was wrong:",
	correctedSqlLabel: "Corrected SQL Query:",
	correctedSqlPlaceholder: "Enter the correct SQL query here...",
	commentLabel: "Comment (optional):",
	commentPlaceholder: "Explain what was wrong with the original query...",
	cancelButton: "Cancel",
	submitButton: "Submit Feedback",
	submittingButton: "Submitting...",
	correctedSqlRequired: "Please provide a corrected SQL query.",
	feedbackError: "Failed to submit feedback. Please try again.",
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

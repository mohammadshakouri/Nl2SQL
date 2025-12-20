export const enum ServerEventType {
	Message = "1",
	Feedback = "2",
	Search = "4",
}

export const baseUrl =
	import.meta.env.MODE === "development" ? "http://localhost:80" : window.location.origin;

export function GetCurrentTimeString() {
	const now = new Date();
	const hours = now.getHours().toString().padStart(2, "0");
	const minutes = now.getMinutes().toString().padStart(2, "0");
	return `${hours}:${minutes}`;
}

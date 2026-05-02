/**
 * Configuration file for the NL2SQL chatbot
 */

export const config = {
	/**
	 * API key for authenticating with the FastAPI backend
	 * This should match the SIMAC_API_KEY in your backend .env file
	 */
	apiKey: import.meta.env.VITE_API_KEY || "simac-QnrxndWE8iZ3pYLUj36CweOG7nXtkcuVrm9cXSvi0sHArALsY9",

	/**
	 * Schema name for the database
	 * Options: 'ecommerce', 'hr', 'inventory', etc.
	 */
	// schemaName: import.meta.env.VITE_SCHEMA_NAME || "transactions",
	schemaName: import.meta.env.VITE_SCHEMA_NAME || "simacnashr",

	/**
	 * Whether to validate SQL execution on the backend
	 */
	validateExecution: true,
};

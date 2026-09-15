import { staticRequest } from "./static";

export class APIError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "APIError";
  }
}

// Callback for handling 401 errors


export function setUnauthorizedCallback(_callback: () => void) {}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  return staticRequest<T>(endpoint, options);
}

async function get<T>(endpoint: string): Promise<T> {
  return request<T>(endpoint, { method: "GET" });
}

async function post<T>(endpoint: string, data?: unknown): Promise<T> {
  return request<T>(endpoint, {
    method: "POST",
    body: data ? JSON.stringify(data) : undefined,
  });
}

async function patch<T>(endpoint: string, data?: unknown): Promise<T> {
  return request<T>(endpoint, {
    method: "PATCH",
    body: data ? JSON.stringify(data) : undefined,
  });
}

async function del<T>(endpoint: string): Promise<T> {
  return request<T>(endpoint, { method: "DELETE" });
}

export const api = {
  get,
  post,
  patch,
  delete: del,
};

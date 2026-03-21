/**
 * useAuth — Simple passcode authentication hook
 * Stores session token in localStorage with 8-hour TTL
 */

import { useState, useEffect } from 'react';

const PASSCODE = process.env.NEXT_PUBLIC_DASHBOARD_PASSCODE || '1234';
const SESSION_KEY = 'wagmi_auth_token';
const SESSION_TTL = 8 * 60 * 60 * 1000; // 8 hours

export interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (passcode: string) => Promise<boolean>;
  logout: () => void;
}

export function useAuth(): AuthState {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Check session on mount
  useEffect(() => {
    const token = localStorage.getItem(SESSION_KEY);
    if (token) {
      const [createdAt] = token.split(':');
      const age = Date.now() - parseInt(createdAt, 10);
      if (age < SESSION_TTL) {
        setIsAuthenticated(true);
      } else {
        // Token expired
        localStorage.removeItem(SESSION_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  const login = async (passcode: string): Promise<boolean> => {
    setError(null);
    if (passcode === PASSCODE) {
      const token = `${Date.now()}:${Math.random().toString(36).substring(7)}`;
      localStorage.setItem(SESSION_KEY, token);
      setIsAuthenticated(true);
      return true;
    } else {
      setError('Incorrect passcode');
      return false;
    }
  };

  const logout = () => {
    localStorage.removeItem(SESSION_KEY);
    setIsAuthenticated(false);
    setError(null);
  };

  return { isAuthenticated, isLoading, error, login, logout };
}

#!/usr/bin/python3
import argparse, sys
import msal  # pip install msal
import urllib.parse

class TokenManager:
    def __init__(self, client_id, user, authority="https://login.microsoftonline.com/consumers", 
                 scope="https://outlook.office.com/POP.AccessAsUser.All"):
        self.client_id = client_id
        self.user = user
        self.authority = authority
        self.scope = scope
        self.app = msal.PublicClientApplication(client_id, authority=authority)

    def get_device_flow_url_and_code(self):
        """Initiate device flow and return the verification URL and user code"""
        flow = self.app.initiate_device_flow(scopes=[self.scope])
        if "user_code" not in flow:
            raise Exception(f"Failed to start device flow: {flow}")
        return flow

    def get_auth_url(self, redirect_uri):
        """Get the authorization URL for web-based flow"""
        auth_url = self.app.get_authorization_request_url(
            scopes=[self.scope],
            redirect_uri=redirect_uri
        )
        return auth_url

    def acquire_token_by_auth_code(self, auth_code, redirect_uri):
        """Acquire token using authorization code from web flow"""
        result = self.app.acquire_token_by_authorization_code(
            auth_code,
            scopes=[self.scope],
            redirect_uri=redirect_uri
        )
        if "access_token" not in result:
            raise Exception(result.get("error_description", result))
        return result

    def acquire_token_by_device_flow(self, flow):
        """Acquire token using device flow"""
        result = self.app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise Exception(result.get("error_description", result))
        return result

    def format_netrc_entry(self, refresh_token):
        """Format the token as .netrc entry"""
        return f"""machine outlook.office365.com
  login {self.user}
  account MSAL:{self.client_id}
  password {refresh_token}"""

def main_cli(client_id='60da67f7-5fde-4e85-baf3-ab28d0c8e034', user='jsr_critchley@hotmail.com', authority="https://login.microsoftonline.com/consumers",
            scope="https://outlook.office.com/POP.AccessAsUser.All"):
    """Command line interface function"""
    try:
        token_manager = TokenManager(client_id, user, authority, scope)
        flow = token_manager.get_device_flow_url_and_code()
        print(flow["message"])  # follow the URL and paste the code
        
        result = token_manager.acquire_token_by_device_flow(flow)
        rt = result.get("refresh_token")
        if not rt:
            sys.exit("No refresh_token returned. Try again or enable device flow/public client in the app.")

        print("\n# Add this to your ~/.netrc (permissions 600):\n")
        print(token_manager.format_netrc_entry(rt))
        print("\n# If you also want IMAP later, you can reuse the same refresh token.\n")
        
    except Exception as e:
        sys.exit(f"Error: {e}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Acquire a refresh token for POP via device code and print .netrc lines.")
    ap.add_argument(
        "--client-id",
        default="60da67f7-5fde-4e85-baf3-ab28d0c8e034",
        help="Application (client) ID of your Azure app (from app registration or service principal)."
    )

    ap.add_argument(
        "--user",
        default="jsr_critchley@hotmail.com",
        help="Email address you'll use with POP (e.g. Hotmail/Outlook alias). "
             "Example: jsr_critchley@hotmail.com"
    )

    ap.add_argument(
        "--authority",
        default="https://login.microsoftonline.com/consumers",
        help="Azure AD authority endpoint. Use 'consumers' for Hotmail/Outlook personal accounts, "
             "'organizations' for work/school accounts, or your tenant ID for tenant-specific login."
    )

    ap.add_argument(
        "--scope",
        default="https://outlook.office.com/POP.AccessAsUser.All",
        help="OAuth2 permission scope to request. For POP access, use POP.AccessAsUser.All; "
             "for IMAP or SMTP set the corresponding scope instead."
    )
    ns = ap.parse_args()
    main_cli(**vars(ns))

import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export default function DataDeletion() {
  return (
    <div className="legal-page">
      <div className="legal-container">
        <Link to="/" className="legal-back">
          <ArrowLeft size={16} /> Back
        </Link>

        <h1>Data Deletion Instructions</h1>
        <p className="legal-updated">Last updated: August 2026</p>

        <p>
          CreditVoice Technology Services respects your right to control your personal data under the Nigeria Data Protection Act (NDPA) 2023. This page explains how to delete your CreditVoice / tiTi account and the personal data associated with it.
        </p>

        <section>
          <h2>1. Delete your account in the app</h2>
          <p>
            The fastest way to delete your data is from your account:
          </p>
          <ul>
            <li>Open the CreditVoice web app and sign in.</li>
            <li>Go to <strong>My Profile</strong> in the menu.</li>
            <li>Choose <strong>Delete my account</strong> and confirm.</li>
          </ul>
          <p>
            This permanently erases your personal data in line with your NDPA right to erasure.
          </p>
        </section>

        <section>
          <h2>2. Request deletion by email</h2>
          <p>
            If you can’t access the app, email us at <a href="mailto:support@creditvoiceai.com">support@creditvoiceai.com</a> from the email address or with the phone number registered to your account, using the subject line <strong>“Delete my account”</strong>. We will verify your identity and process the request.
          </p>
        </section>

        <section>
          <h2>3. What gets deleted</h2>
          <ul>
            <li>Your account details (name, phone number, email, business profile, PIN).</li>
            <li>The business records you created (sales, payments, customers, inventory, suppliers) and messages you sent to tiTi.</li>
          </ul>
          <p>
            Once deleted, this data cannot be recovered.
          </p>
        </section>

        <section>
          <h2>4. Timeframe &amp; exceptions</h2>
          <p>
            After you request deletion, your data is retained for up to <strong>30 days</strong> (in case you change your mind) and then permanently deleted. We may retain a limited amount of information for longer where required to comply with a legal or regulatory obligation, after which it is deleted.
          </p>
        </section>

        <section>
          <h2>5. Contact</h2>
          <p>
            For any question about deleting your data, contact us at <a href="mailto:support@creditvoiceai.com">support@creditvoiceai.com</a>. See also our <Link to="/privacy">Privacy Policy</Link>.
          </p>
        </section>

        <div className="legal-copyright">
          © {new Date().getFullYear()} CreditVoice Technology Services. All rights reserved.
        </div>
      </div>
    </div>
  );
}

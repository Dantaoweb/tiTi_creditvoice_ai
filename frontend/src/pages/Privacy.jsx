import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export default function Privacy() {
  return (
    <div className="legal-page">
      <div className="legal-container">
        <Link to="/" className="legal-back">
          <ArrowLeft size={16} /> Back
        </Link>

        <h1>Privacy Policy</h1>
        <p className="legal-updated">Last updated: August 2026</p>

        <p>
          CreditVoice Technology Services is committed to protecting your privacy in compliance with the Nigeria Data Protection Act (NDPA) 2023. This policy explains how we collect, use, and protect your personal data when you use CreditVoice and tiTi.
        </p>

        <section>
          <h2>1. Who We Are</h2>
          <p>
            CreditVoice is a business management platform for small and medium scale enterprises (SMEs) in Nigeria. This policy explains how we handle your personal information under the NDPA.
          </p>
        </section>

        <section>
          <h2>2. Data We Collect</h2>
          <p>We may collect the following information:</p>
          <ul>
            <li><strong>Account data:</strong> Your name, phone number, email address (optional), business name, business type, address, and PIN</li>
            <li><strong>Business records:</strong> Sales, payments, inventory items, customer names and phone numbers, and supplier information that you enter</li>
            <li><strong>Messages:</strong> Text and voice messages you send to tiTi on WhatsApp or the web app</li>
            <li><strong>Automatic data:</strong> IP address, device type, browser information, approximate location (country level), and app usage patterns</li>
            <li><strong>Third-party data:</strong> Information from partner platforms you use to access our services (e.g. WhatsApp/Meta)</li>
          </ul>
        </section>

        <section>
          <h2>3. How We Use Your Data</h2>
          <ul>
            <li>To provide, operate, and improve our services, including AI-powered features (tiTi)</li>
            <li>To personalise your experience and recommendations</li>
            <li>To communicate with you about your account, alerts, reminders, and our services</li>
            <li>To ensure platform security and prevent fraud</li>
            <li>To comply with legal obligations</li>
          </ul>
          <p>
            We do <strong>not</strong> sell your personal data to third parties or use it for advertising.
          </p>
        </section>

        <section>
          <h2>4. Lawful Basis for Processing</h2>
          <p>We process your data based on:</p>
          <ul>
            <li>Your consent</li>
            <li>Performance of a contract</li>
            <li>Our legitimate interests (not overridden by your rights)</li>
            <li>Compliance with legal obligations</li>
          </ul>
        </section>

        <section>
          <h2>5. AI and Your Messages</h2>
          <p>
            Messages you send to tiTi are processed by AI models (Claude by Anthropic; OpenAI Whisper for voice) to interpret transactions and provide business insights. These messages may be reviewed in anonymised form to improve tiTi's accuracy.
          </p>
          <p>
            tiTi can make mistakes. Please verify important records and figures yourself.
          </p>
        </section>

        <section>
          <h2>6. Data Sharing</h2>
          <p>We do <strong>not</strong> sell your personal data. We may share it with:</p>
          <ul>
            <li><strong>Service providers</strong> who process data on our behalf under strict contract (cloud hosting, email delivery, AI providers)</li>
            <li><strong>Partner platforms</strong> you use to access our services — messages sent via WhatsApp are subject to Meta's privacy policy</li>
            <li><strong>Legal authorities</strong>, only when required by Nigerian law with a valid legal order</li>
            <li><strong>A new entity</strong>, in the event of a merger or acquisition</li>
          </ul>
        </section>

        <section>
          <h2>7. Your Customer Data</h2>
          <p>
            Information about your customers (names, phone numbers, balances) that you store in CreditVoice belongs to you. We process it only to provide the service. You are responsible for ensuring you have the right to store and process your customers' information.
          </p>
        </section>

        <section>
          <h2>8. Data Security and Retention</h2>
          <p>
            We implement technical and organisational security measures, including encrypted connections (HTTPS), hashed PINs, and signed session tokens. No system is 100% secure — if you suspect your account has been compromised, contact us immediately.
          </p>
          <p>
            We retain your data only as long as needed for the purposes it was collected or to comply with legal obligations. If you delete your account, your data is retained for 30 days before permanent deletion, in case you change your mind.
          </p>
        </section>

        <section>
          <h2>9. International Data Transfers</h2>
          <p>
            Where personal data is transferred outside Nigeria (for example, to AI or cloud-hosting providers), we ensure adequate safeguards are in place in compliance with the NDPA.
          </p>
        </section>

        <section>
          <h2>10. Your Rights (NDPA)</h2>
          <p>You have the right to:</p>
          <ul>
            <li>Access, correct, or delete your personal data</li>
            <li>Restrict or object to processing</li>
            <li>Request data portability (export your business records from the dashboard)</li>
            <li>Withdraw consent at any time, without affecting the lawfulness of prior processing</li>
            <li>Lodge a complaint with the Nigeria Data Protection Commission (NDPC)</li>
          </ul>
          <p>To exercise your rights, contact us at <a href="mailto:support@creditvoiceai.com">support@creditvoiceai.com</a>.</p>
        </section>

        <section>
          <h2>11. Cookies</h2>
          <p>
            The web app uses local storage (not third-party cookies) to keep you logged in and save your preferences. We do not use tracking or advertising cookies.
          </p>
        </section>

        <section>
          <h2>12. Changes to This Policy</h2>
          <p>
            We may update this policy from time to time. We will notify you of material changes within the app or via email/WhatsApp. Continued use after changes signifies acceptance.
          </p>
        </section>

        <section>
          <h2>13. Contact Us</h2>
          <p>
            For questions or requests about this policy, contact us at <a href="mailto:support@creditvoiceai.com">support@creditvoiceai.com</a>.
          </p>
        </section>

        <div className="legal-copyright">
          © {new Date().getFullYear()} CreditVoice Technology Services. All rights reserved.<br />
          CreditVoice AI is a product of CreditVoice Technology Services.
        </div>
      </div>
    </div>
  );
}

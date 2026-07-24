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
        <p className="legal-updated">Last updated: June 2026</p>

        <section>
          <h2>1. Who We Are</h2>
          <p>
            CreditVoice is a business management platform for informal and small businesses in Nigeria. This policy explains how we collect, use, and protect your personal information.
          </p>
        </section>

        <section>
          <h2>2. What We Collect</h2>
          <p>We collect the following information:</p>
          <ul>
            <li><strong>Account data:</strong> Your name, phone number, email address (optional), business name, and business type</li>
            <li><strong>Business records:</strong> Sales, payments, inventory items, customer names and phone numbers, and supplier information that you enter</li>
            <li><strong>Messages:</strong> Text and voice messages you send to tiTi on WhatsApp or the web app</li>
            <li><strong>Usage data:</strong> How you use the platform (pages visited, features used) to help us improve</li>
            <li><strong>Device data:</strong> Browser type and approximate location (country level only)</li>
          </ul>
        </section>

        <section>
          <h2>3. How We Use Your Data</h2>
          <ul>
            <li>To provide and operate the CreditVoice service</li>
            <li>To power tiTi — the AI assistant that reads your messages to record transactions</li>
            <li>To improve the accuracy of tiTi using anonymised conversation patterns</li>
            <li>To send you alerts, reminders, and notifications you have enabled</li>
            <li>To comply with legal obligations</li>
          </ul>
          <p>
            We do <strong>not</strong> sell your personal data to third parties or use it for advertising.
          </p>
        </section>

        <section>
          <h2>4. AI and Your Messages</h2>
          <p>
            Messages you send to tiTi are processed by AI models (Claude by Anthropic, OpenAI Whisper for voice) to interpret transactions and provide business insights. These messages may be reviewed in anonymised form to improve tiTi's accuracy.
          </p>
          <p>
            tiTi can make mistakes. Please verify important records and figures yourself.
          </p>
        </section>

        <section>
          <h2>5. Data Sharing</h2>
          <p>We share data only with:</p>
          <ul>
            <li><strong>Service providers</strong> who help us operate the platform (cloud hosting, email delivery, AI providers) — bound by data processing agreements</li>
            <li><strong>WhatsApp / Meta</strong> — messages sent via WhatsApp are subject to Meta's privacy policy</li>
            <li><strong>Law enforcement</strong> — only when required by Nigerian law with a valid legal order</li>
          </ul>
        </section>

        <section>
          <h2>6. Your Customer Data</h2>
          <p>
            Information about your customers (names, phone numbers, balances) that you store in CreditVoice belongs to you. We process it only to provide the service. You are responsible for ensuring you have the right to store and process your customers' information.
          </p>
        </section>

        <section>
          <h2>7. Data Security</h2>
          <p>
            We use industry-standard security measures including encrypted connections (HTTPS), hashed PINs, and signed session tokens. No system is 100% secure — if you suspect your account has been compromised, contact us immediately.
          </p>
        </section>

        <section>
          <h2>8. Data Retention</h2>
          <p>
            We keep your data for as long as your account is active. If you delete your account, your data is retained for 30 days before permanent deletion, in case you change your mind.
          </p>
        </section>

        <section>
          <h2>9. Your Rights</h2>
          <p>You have the right to:</p>
          <ul>
            <li>Access the data we hold about you</li>
            <li>Correct inaccurate data</li>
            <li>Request deletion of your account and data</li>
            <li>Export your business records (available from the dashboard)</li>
          </ul>
          <p>To exercise these rights, contact us at <a href="mailto:support@creditvoiceai.com">support@creditvoiceai.com</a>.</p>
        </section>

        <section>
          <h2>10. Cookies</h2>
          <p>
            The web app uses local storage (not third-party cookies) to keep you logged in and save your preferences. We do not use tracking or advertising cookies.
          </p>
        </section>

        <section>
          <h2>11. Changes to This Policy</h2>
          <p>
            We may update this policy from time to time. We will notify you via WhatsApp or email when significant changes are made.
          </p>
        </section>

        <section>
          <h2>12. Contact</h2>
          <p>
            For privacy questions or requests, contact us at <a href="mailto:support@creditvoiceai.com">support@creditvoiceai.com</a>.
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

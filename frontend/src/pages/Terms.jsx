import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export default function Terms() {
  return (
    <div className="legal-page">
      <div className="legal-container">
        <Link to="/" className="legal-back">
          <ArrowLeft size={16} /> Back
        </Link>

        <h1>Terms of Service</h1>
        <p className="legal-updated">Last updated: June 2026</p>

        <section>
          <h2>1. Acceptance of Terms</h2>
          <p>
            By accessing or using CreditVoice ("the Service"), you agree to be bound by these Terms of Service. If you do not agree, please do not use the Service.
          </p>
        </section>

        <section>
          <h2>2. What CreditVoice Does</h2>
          <p>
            CreditVoice provides small and informal business owners with tools to record sales, track customer debts, manage inventory, and receive business insights via WhatsApp (tiTi) and a web application. It is not a banking, lending, or financial advice service.
          </p>
        </section>

        <section>
          <h2>3. Your Account</h2>
          <p>
            You are responsible for keeping your PIN and account credentials secure. You must not share your account with others or allow unauthorised access. CreditVoice is not liable for losses caused by unauthorised use of your account.
          </p>
          <p>
            Your account is tied to your WhatsApp phone number. If you lose access to that number, contact us immediately.
          </p>
        </section>

        <section>
          <h2>4. Acceptable Use</h2>
          <p>You agree not to:</p>
          <ul>
            <li>Use the Service for illegal or fraudulent activities</li>
            <li>Attempt to reverse-engineer or hack the platform</li>
            <li>Misuse the AI assistant (tiTi) to generate false records</li>
            <li>Resell access to the Service without written permission</li>
          </ul>
        </section>

        <section>
          <h2>5. AI-Generated Content</h2>
          <p>
            tiTi uses artificial intelligence to help record and interpret your business data. While we work to make tiTi accurate, AI can make mistakes. <strong>You are responsible for verifying all figures and records</strong>. CreditVoice is not liable for errors arising from AI misinterpretation of your messages.
          </p>
          <p>
            Your interactions with tiTi may be used to improve the accuracy of the AI system. See our Privacy Policy for how this data is handled.
          </p>
        </section>

        <section>
          <h2>6. Subscription Plans</h2>
          <p>
            CreditVoice offers free (Basic) and paid (Go, Pro) plans. Paid plans are billed as described on the pricing page. We reserve the right to change pricing with 30 days' notice. Refunds are not provided for partially used subscription periods unless required by applicable law.
          </p>
        </section>

        <section>
          <h2>7. Data Ownership</h2>
          <p>
            You own your business data. CreditVoice does not sell your data to third parties. We may use anonymised, aggregated data to improve the platform. See our Privacy Policy for full details.
          </p>
        </section>

        <section>
          <h2>8. Service Availability</h2>
          <p>
            We aim for high availability but cannot guarantee uninterrupted access. We are not liable for losses resulting from downtime, data loss, or service interruptions.
          </p>
        </section>

        <section>
          <h2>9. Termination</h2>
          <p>
            We may suspend or terminate your account if you violate these terms. You may delete your account at any time by contacting support. On termination, your data will be retained for 30 days before deletion.
          </p>
        </section>

        <section>
          <h2>10. Governing Law</h2>
          <p>
            These terms are governed by the laws of the Federal Republic of Nigeria. Any disputes shall be resolved in Nigerian courts.
          </p>
        </section>

        <section>
          <h2>11. Contact</h2>
          <p>
            For questions about these terms, contact us at <a href="mailto:support@creditvoice.ng">support@creditvoice.ng</a>.
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

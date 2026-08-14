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
        <p className="legal-updated">Last updated: August 2026</p>

        <p className="legal-notice">
          PLEASE READ THESE TERMS CAREFULLY BEFORE USING CREDITVOICE. BY ACCESSING OR USING THE APP, YOU AGREE TO BE BOUND BY THESE TERMS. IF YOU DO NOT AGREE, DO NOT USE THE APP.
        </p>

        <p>
          These Terms of Service ("Terms") are a binding legal agreement between you (the "User") and CreditVoice Technology Services, operating creditvoiceai.com (the "Company", "we", "us"). They apply to individual end-users and businesses using CreditVoice and tiTi.
        </p>

        <section>
          <h2>1. Acceptance of Terms</h2>
          <p>
            By creating an account or using the App via WhatsApp (tiTi) or the web application, you agree to these Terms and to our Privacy Policy. If you use the App on behalf of a business, you confirm you are authorised to bind that business to these Terms.
          </p>
        </section>

        <section>
          <h2>2. Eligibility and Account</h2>
          <p>
            You must be at least 18 years old to use the App. You are responsible for keeping your account and PIN confidential and for all activity under your account. You agree to provide accurate and complete information and to keep it up to date, and to notify us immediately of any unauthorised use of your account.
          </p>
        </section>

        <section>
          <h2>3. What CreditVoice Does</h2>
          <p>
            CreditVoice provides small and medium scale enterprises (SMEs) with tools to record sales, track customer debts, manage inventory, and receive business insights via WhatsApp (tiTi) and a web application. It is a record-keeping and business-management tool. It is <strong>not</strong> a banking, lending, tax, accounting, or financial-advice service, and nothing in the App constitutes professional financial or legal advice.
          </p>
        </section>

        <section>
          <h2>4. Your Data and Content</h2>
          <p>
            You retain ownership of the data and content you submit ("User Data"). You grant the Company a limited, worldwide, royalty-free licence to host, process, and display your User Data solely to operate, secure, and improve the App and to provide it back to you.
          </p>
          <p>
            Any use of data for research, analytics, or promotion is limited to <strong>aggregated or anonymised</strong> data that does not identify you or your customers. We do <strong>not</strong> sell your User Data. You warrant that you have the necessary rights to submit your User Data and that it does not infringe any third-party rights or applicable Nigerian law.
          </p>
        </section>

        <section>
          <h2>5. AI-Generated Content</h2>
          <p>
            tiTi uses artificial intelligence to interpret your messages and generate records, summaries, and insights. AI can make mistakes. You are responsible for reviewing and verifying important records, figures, and decisions. The Company is not liable for losses arising from reliance on AI-generated output without verification.
          </p>
        </section>

        <section>
          <h2>6. Acceptable Use and Restrictions</h2>
          <p>You agree not to misuse the App. In particular, you must not:</p>
          <ul>
            <li>violate any applicable law or infringe intellectual property or privacy rights</li>
            <li>transmit harmful, fraudulent, or offensive material</li>
            <li>attempt to breach the App's security, or access data that is not yours</li>
            <li>reverse-engineer, copy, or resell the software or service</li>
          </ul>
        </section>

        <section>
          <h2>7. Proprietary Rights</h2>
          <p>
            The Company owns all rights, title, and interest in the App and its content (excluding your User Data), including any feedback you provide. You may not use the Company's name, logos, or trademarks without prior written consent.
          </p>
        </section>

        <section>
          <h2>8. Fees, Taxes and Subscriptions</h2>
          <p>
            CreditVoice offers a free tier and paid subscription plans. Current features and pricing are shown within the App and may change on notice. Fees, where applicable, are non-refundable except where required by law, and are exclusive of applicable taxes (including Value Added Tax), for which you are solely responsible.
          </p>
        </section>

        <section>
          <h2>9. Termination</h2>
          <p>
            You may terminate these Terms at any time by deleting your account. We may suspend or terminate your access, with or without notice, for breach of these Terms or where reasonably necessary to protect the service or other users. On termination, your data is handled as described in our Privacy Policy.
          </p>
        </section>

        <section>
          <h2>10. Warranty Disclaimer</h2>
          <p>
            THE APP IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR NON-INFRINGEMENT. THE COMPANY DOES NOT GUARANTEE THAT THE APP WILL BE ERROR-FREE, SECURE, OR UNINTERRUPTED.
          </p>
        </section>

        <section>
          <h2>11. Indemnity</h2>
          <p>
            YOU AGREE TO INDEMNIFY AND HOLD HARMLESS THE COMPANY AGAINST ALL CLAIMS, DAMAGES, AND REASONABLE EXPENSES (INCLUDING LEGAL FEES) ARISING FROM YOUR BREACH OF THESE TERMS, YOUR MISUSE OF THE APP, OR YOUR VIOLATION OF ANY LAW OR THIRD-PARTY RIGHTS.
          </p>
        </section>

        <section>
          <h2>12. Limitation of Liability</h2>
          <p>
            TO THE MAXIMUM EXTENT PERMITTED BY NIGERIAN LAW, THE COMPANY SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES, OR FOR ANY LOSS OF PROFITS, DATA, OR BUSINESS, ARISING FROM THESE TERMS OR THE APP. THE COMPANY'S MAXIMUM CUMULATIVE LIABILITY SHALL NOT EXCEED THE TOTAL FEES YOU PAID TO THE COMPANY IN THE THREE (3) MONTHS PRECEDING THE CLAIM.
          </p>
        </section>

        <section>
          <h2>13. Governing Law and Dispute Resolution</h2>
          <p>
            These Terms are governed by the laws of the Federal Republic of Nigeria. Any dispute arising out of or relating to these Terms shall first be resolved through good-faith negotiation. If the dispute is not resolved within thirty (30) days, it shall be finally settled by binding arbitration under the Arbitration and Mediation Act 2023.
          </p>
          <p>
            The arbitration shall be conducted in English, before a single arbitrator, with the seat of arbitration in Nigeria. Both parties waive any right to participate in a class action. Either party may seek interim injunctive relief from a court of competent jurisdiction.
          </p>
        </section>

        <section>
          <h2>14. General Provisions</h2>
          <p>
            These Terms constitute the entire agreement between you and the Company and supersede all prior agreements. We may modify these Terms and will notify you by posting the updated version in the App or by email/WhatsApp; continued use after changes constitutes acceptance. If any provision is found invalid, the remaining provisions remain in full force. You may not assign these Terms without our consent.
          </p>
        </section>

        <section>
          <h2>15. Contact</h2>
          <p>
            For questions about these Terms, contact us at <a href="mailto:support@creditvoiceai.com">support@creditvoiceai.com</a>.
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

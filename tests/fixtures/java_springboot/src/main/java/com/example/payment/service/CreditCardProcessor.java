package com.example.payment.service;

import com.example.payment.domain.CreditCardPayment;
import com.example.payment.domain.Payment;
import com.example.payment.domain.PaymentStatus;
import com.example.payment.domain.PaymentType;
import org.springframework.stereotype.Service;

@Service
public class CreditCardProcessor implements PaymentProcessor<CreditCardPayment> {
    
    @Override
    public void process(CreditCardPayment payment) {
        if (payment.validate()) {
            // Simulate payment gateway integration
            boolean success = chargeCard(payment);
            if (success) {
                payment.setStatus(PaymentStatus.COMPLETED);
            } else {
                payment.setStatus(PaymentStatus.FAILED);
            }
        }
    }

    @Override
    public boolean canProcess(Payment payment) {
        return payment.getType() == PaymentType.CREDIT_CARD;
    }

    @Override
    public void refund(CreditCardPayment payment) {
        if (payment.getStatus() == PaymentStatus.COMPLETED) {
            payment.setStatus(PaymentStatus.REFUNDED);
        }
    }

    private boolean chargeCard(CreditCardPayment payment) {
        // Simulate external API call
        return true;
    }
}

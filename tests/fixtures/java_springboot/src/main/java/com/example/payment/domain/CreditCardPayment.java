package com.example.payment.domain;

import java.math.BigDecimal;

public class CreditCardPayment extends Payment {
    private String cardNumber;
    private String cardHolderName;
    private String cvv;
    private String expiryDate;

    public CreditCardPayment(String id, BigDecimal amount, String currency,
                            String cardNumber, String cardHolderName, 
                            String cvv, String expiryDate) {
        super(id, amount, currency);
        this.cardNumber = maskCardNumber(cardNumber);
        this.cardHolderName = cardHolderName;
        this.cvv = cvv;
        this.expiryDate = expiryDate;
    }

    @Override
    public PaymentType getType() {
        return PaymentType.CREDIT_CARD;
    }

    @Override
    public boolean validate() {
        return validateCardNumber() && validateCVV() && validateExpiry();
    }

    private boolean validateCardNumber() {
        return cardNumber != null && cardNumber.length() >= 13;
    }

    private boolean validateCVV() {
        return cvv != null && cvv.matches("\\d{3,4}");
    }

    private boolean validateExpiry() {
        return expiryDate != null && expiryDate.matches("\\d{2}/\\d{2}");
    }

    private String maskCardNumber(String cardNumber) {
        if (cardNumber == null || cardNumber.length() < 4) {
            return cardNumber;
        }
        return "**** **** **** " + cardNumber.substring(cardNumber.length() - 4);
    }

    public String getCardNumber() {
        return cardNumber;
    }
}

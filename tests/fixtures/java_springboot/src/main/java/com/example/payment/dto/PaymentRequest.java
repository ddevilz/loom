package com.example.payment.dto;

import com.example.payment.domain.*;
import java.math.BigDecimal;

public class PaymentRequest {
    private String type;
    private BigDecimal amount;
    private String currency;
    private String cardNumber;
    private String cardHolderName;
    private String cvv;
    private String expiryDate;
    private String accountNumber;
    private String routingNumber;
    private String bankName;

    public Payment toPayment() {
        String id = java.util.UUID.randomUUID().toString();
        
        if ("CREDIT_CARD".equals(type)) {
            return new CreditCardPayment(id, amount, currency, 
                    cardNumber, cardHolderName, cvv, expiryDate);
        } else if ("BANK_TRANSFER".equals(type)) {
            return new BankTransferPayment(id, amount, currency,
                    accountNumber, routingNumber, bankName);
        }
        
        throw new IllegalArgumentException("Unsupported payment type: " + type);
    }

    // Getters and setters
    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }
    public String getCurrency() { return currency; }
    public void setCurrency(String currency) { this.currency = currency; }
}
